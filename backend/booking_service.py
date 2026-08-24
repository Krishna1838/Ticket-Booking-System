import uuid
import json
from datetime import datetime, timedelta
from sqlalchemy import text
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from backend import models, email_service
from backend.websocket_manager import manager

async def broadcast_seat_update(event_id: int, db: Session, seat_ids: list[int]):
    """
    Helper to fetch the current state of specific seats and broadcast it via WebSocket.
    """
    event_seats = (
        db.query(models.EventSeat)
        .join(models.Seat)
        .filter(models.EventSeat.event_id == event_id, models.EventSeat.seat_id.in_(seat_ids))
        .all()
    )
    
    seats_data = []
    for es in event_seats:
        seats_data.append({
            "seat_id": es.seat_id,
            "row_name": es.seat.row_name,
            "seat_number": es.seat.seat_number,
            "category": es.seat.category,
            "status": es.status,
            "expires_at": es.expires_at.isoformat() if es.expires_at else None
        })
        
    await manager.broadcast_event_update(event_id, {
        "type": "seat_update",
        "seats": seats_data
    })

def check_category_sold_out(db: Session, event_id: int, category: str) -> bool:
    """
    Checks if a seat category for an event is completely sold out (all seats booked or actively held).
    """
    total_seats = (
        db.query(models.Seat)
        .join(models.Venue)
        .join(models.Event, models.Event.venue_id == models.Venue.id)
        .filter(models.Event.id == event_id, models.Seat.category == category)
        .count()
    )
    
    active_held_or_booked = (
        db.query(models.EventSeat)
        .join(models.Seat)
        .filter(
            models.EventSeat.event_id == event_id,
            models.Seat.category == category,
            (models.EventSeat.status == "booked") | 
            ((models.EventSeat.status == "held") & (models.EventSeat.expires_at >= datetime.utcnow()))
        )
        .count()
    )
    
    return active_held_or_booked >= total_seats

async def hold_seats(db: Session, user_id: int, event_id: int, seat_ids: list[int]) -> list[models.EventSeat]:
    """
    Transactional hold on seats for 10 minutes.
    """
    if not seat_ids:
        raise HTTPException(status_code=400, detail="No seats selected")

    # Enforce database write serialization for concurrency protection
    db.execute(text("BEGIN IMMEDIATE"))
    
    try:
        now = datetime.utcnow()
        # Fetch event seats to verify eligibility
        event_seats = (
            db.query(models.EventSeat)
            .filter(models.EventSeat.event_id == event_id, models.EventSeat.seat_id.in_(seat_ids))
            .all()
        )
        
        if len(event_seats) != len(seat_ids):
            raise HTTPException(status_code=404, detail="One or more seats not found for this event")
            
        for es in event_seats:
            is_held = es.status == "held" and es.expires_at and es.expires_at >= now
            is_booked = es.status == "booked"
            
            if is_booked or is_held:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Seat {es.seat.row_name}-{es.seat.seat_number} is already booked or held."
                )
        
        # Set holds
        hold_expiry = now + timedelta(minutes=10)
        for es in event_seats:
            es.status = "held"
            es.user_id = user_id
            es.expires_at = hold_expiry
            
        db.commit()
    except Exception as e:
        db.rollback()
        raise e

    # Broadcast status change
    await broadcast_seat_update(event_id, db, seat_ids)
    return event_seats

async def confirm_booking(db: Session, user_id: int, event_id: int, seat_ids: list[int]) -> str:
    """
    Transactional conversion of seat holds to confirmed booking.
    """
    if not seat_ids:
        raise HTTPException(status_code=400, detail="No seats selected")
        
    db.execute(text("BEGIN IMMEDIATE"))
    
    try:
        now = datetime.utcnow()
        event = db.query(models.Event).filter(models.Event.id == event_id).first()
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
            
        pricing = json.loads(event.pricing)
        
        event_seats = (
            db.query(models.EventSeat)
            .filter(models.EventSeat.event_id == event_id, models.EventSeat.seat_id.in_(seat_ids))
            .all()
        )
        
        if len(event_seats) != len(seat_ids):
            raise HTTPException(status_code=404, detail="One or more seats not found")
            
        total_price = 0.0
        for es in event_seats:
            # Must be held by this user and not expired
            is_valid_hold = es.status == "held" and es.user_id == user_id and es.expires_at and es.expires_at >= now
            if not is_valid_hold:
                raise HTTPException(
                    status_code=400,
                    detail=f"Seat {es.seat.row_name}-{es.seat.seat_number} hold is invalid or expired."
                )
            
            category = es.seat.category
            total_price += pricing.get(category, 0.0)
            
        booking_ref = f"BK-{uuid.uuid4().hex[:8].upper()}"
        
        # Mark seats as booked, clear hold time
        for es in event_seats:
            es.status = "booked"
            es.expires_at = None
            
            # Create individual booking record
            booking = models.Booking(
                user_id=user_id,
                event_id=event_id,
                seat_id=es.seat_id,
                booking_reference=booking_ref,
                price_paid=pricing.get(es.seat.category, 0.0),
                status="confirmed"
            )
            db.add(booking)
            
        db.commit()
    except Exception as e:
        db.rollback()
        raise e
        
    # Send booking confirmation email asynchronously (logged/spooled)
    user = db.query(models.User).filter(models.User.id == user_id).first()
    seat_descriptions = [f"{es.seat.row_name}{es.seat.seat_number} ({es.seat.category})" for es in event_seats]
    email_service.send_booking_confirmation(
        recipient_email=user.email,
        booking_ref=booking_ref,
        event_title=event.title,
        date=event.date,
        time=event.time,
        seats=seat_descriptions,
        price=total_price
    )
    
    # Broadcast updates
    await broadcast_seat_update(event_id, db, seat_ids)
    return booking_ref

async def process_waitlist_assignment(db: Session, event_id: int, seat_id: int, seat_category: str):
    """
    Finds the next user in the waitlist queue for this category and directly assigns/books the seat for them,
    since they have already paid upfront.
    Must be called inside an active write transaction.
    """
    next_waitlist = (
        db.query(models.Waitlist)
        .filter(
            models.Waitlist.event_id == event_id,
            models.Waitlist.seat_category == seat_category,
            models.Waitlist.status == "waiting"
        )
        .order_by(models.Waitlist.created_at.asc())  # FIFO queue
        .first()
    )
    
    event_seat = db.query(models.EventSeat).filter(
        models.EventSeat.event_id == event_id,
        models.EventSeat.seat_id == seat_id
    ).first()
    
    if next_waitlist and event_seat:
        # 1. Directly convert the hold to a booking for the waitlist user
        event_seat.status = "booked"
        event_seat.user_id = next_waitlist.user_id
        event_seat.expires_at = None
        
        # 2. Update waitlist status to booked
        next_waitlist.status = "booked"
        
        # 3. Create confirmed booking record
        event = db.query(models.Event).filter(models.Event.id == event_id).first()
        pricing = json.loads(event.pricing)
        price_paid = pricing.get(seat_category, 0.0)
        booking_ref = f"BK-{uuid.uuid4().hex[:8].upper()}"
        
        booking = models.Booking(
            user_id=next_waitlist.user_id,
            event_id=event_id,
            seat_id=seat_id,
            booking_reference=booking_ref,
            price_paid=price_paid,
            status="confirmed"
        )
        db.add(booking)
        
        # 4. Spool confirmed email notification directly with QR code
        user = db.query(models.User).filter(models.User.id == next_waitlist.user_id).first()
        seat_desc = f"{event_seat.seat.row_name}{event_seat.seat.seat_number} ({seat_category})"
        
        email_service.send_booking_confirmation(
            recipient_email=user.email,
            booking_ref=booking_ref,
            event_title=event.title,
            date=event.date,
            time=event.time,
            seats=[seat_desc],
            price=price_paid
        )
        
        # Broadcast the seat update
        await broadcast_seat_update(event_id, db, [seat_id])
    else:
        # No one is waiting, make it available to the public
        if event_seat:
            event_seat.status = "available"
            event_seat.user_id = None
            event_seat.expires_at = None
            await broadcast_seat_update(event_id, db, [seat_id])

async def cancel_booking(db: Session, user_id: int, booking_ref: str):
    """
    Transactional booking cancellation. Returns the event_id.
    """
    db.execute(text("BEGIN IMMEDIATE"))
    
    try:
        bookings = (
            db.query(models.Booking)
            .filter(models.Booking.booking_reference == booking_ref, models.Booking.status == "confirmed")
            .all()
        )
        
        if not bookings:
            raise HTTPException(status_code=404, detail="Booking not found or already cancelled")
            
        # Verify ownership (unless admin)
        requesting_user = db.query(models.User).filter(models.User.id == user_id).first()
        if requesting_user.role != "admin" and bookings[0].user_id != user_id:
            raise HTTPException(status_code=403, detail="Not authorized to cancel this booking")
            
        event_id = bookings[0].event_id
        
        cancelled_seats = []
        for bk in bookings:
            bk.status = "cancelled"
            
            # Retrieve seat status info
            event_seat = (
                db.query(models.EventSeat)
                .filter(models.EventSeat.event_id == event_id, models.EventSeat.seat_id == bk.seat_id)
                .first()
            )
            
            if event_seat:
                # Store seat details to offer it later
                cancelled_seats.append((event_seat.seat_id, event_seat.seat.category))
                
                # Clear booking hold status
                event_seat.status = "available"
                event_seat.user_id = None
                event_seat.expires_at = None
                
        db.commit()
    except Exception as e:
        db.rollback()
        raise e
        
    # Trigger waitlist assignments for the freed seats in separate transactions
    for seat_id, category in cancelled_seats:
        db.execute(text("BEGIN IMMEDIATE"))
        try:
            await process_waitlist_assignment(db, event_id, seat_id, category)
            db.commit()
        except Exception:
            db.rollback()
            # If waitlist auto-assignment fails, the seat will just stay available/unchanged in DB
            pass
            
    return event_id

def join_waitlist(db: Session, user_id: int, event_id: int, seat_category: str) -> models.Waitlist:
    """
    Checks if a category is sold out, and inserts a user into the waitlist queue.
    """
    # Enforce database write serialization
    db.execute(text("BEGIN IMMEDIATE"))
    
    try:
        event = db.query(models.Event).filter(models.Event.id == event_id).first()
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
            
        # 1. Verify category exists in pricing
        pricing = json.loads(event.pricing)
        if seat_category not in pricing:
            raise HTTPException(status_code=400, detail="Invalid seat category for this event")
            
        # 2. Verify that it is actually sold out
        is_sold_out = check_category_sold_out(db, event_id, seat_category)
        if not is_sold_out:
            raise HTTPException(
                status_code=400,
                detail="Category is not sold out. Please book available seats from the map."
            )
            
        # 3. Verify user is not already waiting on this category
        existing = (
            db.query(models.Waitlist)
            .filter(
                models.Waitlist.event_id == event_id,
                models.Waitlist.user_id == user_id,
                models.Waitlist.seat_category == seat_category,
                models.Waitlist.status.in_(["waiting", "offered"])
            )
            .first()
        )
        if existing:
            return existing
            
        waitlist_entry = models.Waitlist(
            user_id=user_id,
            event_id=event_id,
            seat_category=seat_category,
            status="waiting"
        )
        db.add(waitlist_entry)
        db.commit()
        return waitlist_entry
    except Exception as e:
        db.rollback()
        raise e

async def claim_waitlist_offer(db: Session, user_id: int, offer_id: int) -> str:
    """
    Waitlisted user completes booking of their offered seat.
    """
    db.execute(text("BEGIN IMMEDIATE"))
    
    try:
        now = datetime.utcnow()
        offer = (
            db.query(models.Offer)
            .filter(models.Offer.id == offer_id, models.Offer.status == "pending")
            .first()
        )
        
        if not offer:
            raise HTTPException(status_code=404, detail="Offer not found or already processed")
            
        if offer.expires_at < now:
            raise HTTPException(status_code=400, detail="This offer has expired")
            
        waitlist = offer.waitlist
        if waitlist.user_id != user_id:
            raise HTTPException(status_code=403, detail="This offer is not for you")
            
        event = db.query(models.Event).filter(models.Event.id == waitlist.event_id).first()
        pricing = json.loads(event.pricing)
        seat = offer.seat
        
        event_seat = (
            db.query(models.EventSeat)
            .filter(models.EventSeat.event_id == event.id, models.EventSeat.seat_id == offer.seat_id)
            .first()
        )
        
        if not event_seat:
            raise HTTPException(status_code=404, detail="Offered seat not found")
            
        booking_ref = f"BK-{uuid.uuid4().hex[:8].upper()}"
        
        # Update seat to booked
        event_seat.status = "booked"
        event_seat.expires_at = None
        event_seat.user_id = user_id
        
        # Complete offer and waitlist
        offer.status = "completed"
        waitlist.status = "booked"
        
        # Create booking record
        booking = models.Booking(
            user_id=user_id,
            event_id=event.id,
            seat_id=offer.seat_id,
            booking_reference=booking_ref,
            price_paid=pricing.get(seat.category, 0.0),
            status="confirmed"
        )
        db.add(booking)
        db.commit()
    except Exception as e:
        db.rollback()
        raise e
        
    # Send booking confirmation email (logged/spooled)
    user = db.query(models.User).filter(models.User.id == user_id).first()
    seat_desc = f"{seat.row_name}{seat.seat_number} ({seat.category})"
    email_service.send_booking_confirmation(
        recipient_email=user.email,
        booking_ref=booking_ref,
        event_title=event.title,
        date=event.date,
        time=event.time,
        seats=[seat_desc],
        price=pricing.get(seat.category, 0.0)
    )
    
    # Broadcast updates
    await broadcast_seat_update(event.id, db, [offer.seat_id])
    return booking_ref

async def release_seats(db: Session, user_id: int, event_id: int, seat_ids: list[int]):
    """
    Manually release active holds on seats for a user, then trigger waitlist processing.
    """
    if not seat_ids:
        return
        
    db.execute(text("BEGIN IMMEDIATE"))
    released_seats = []
    try:
        event_seats = (
            db.query(models.EventSeat)
            .filter(
                models.EventSeat.event_id == event_id,
                models.EventSeat.seat_id.in_(seat_ids),
                models.EventSeat.status == "held",
                models.EventSeat.user_id == user_id
            )
            .all()
        )
        
        for es in event_seats:
            es.status = "available"
            es.user_id = None
            es.expires_at = None
            released_seats.append((es.seat_id, es.seat.category))
            
        db.commit()
    except Exception as e:
        db.rollback()
        raise e
        
    # Trigger waitlist promotion for each released seat
    for seat_id, category in released_seats:
        db.execute(text("BEGIN IMMEDIATE"))
        try:
            await process_waitlist_assignment(db, event_id, seat_id, category)
            db.commit()
        except Exception:
            db.rollback()
            pass

