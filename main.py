import asyncio
import json
import os
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend import models, schemas, auth, booking_service, scheduler, email_service
from backend.database import engine, Base, get_db
from backend.websocket_manager import manager

# Create database tables on start
Base.metadata.create_all(bind=engine)

def seed_default_users():
    from backend.database import SessionLocal
    db = SessionLocal()
    try:
        if db.query(models.User).count() == 0:
            print("Seeding default account credentials...")
            admin_pwd = auth.get_password_hash("adminpassword")
            cust_pwd = auth.get_password_hash("customerpassword")
            org_pwd = auth.get_password_hash("organiserpassword")
            
            admin = models.User(email="admin@admin.com", hashed_password=admin_pwd, role="admin")
            customer = models.User(email="customer@customer.com", hashed_password=cust_pwd, role="customer")
            organiser = models.User(email="organiser@organiser.com", hashed_password=org_pwd, role="organiser")
            
            db.add_all([admin, customer, organiser])
            db.commit()
            print("Seeding finished successfully!")
    except Exception as e:
        db.rollback()
        print(f"Error seeding default accounts: {e}")
    finally:
        db.close()

seed_default_users()

app = FastAPI(
    title="Ticket Booking System API",
    description="Backend API for managing events, real-time seat holds, waitlists, and bookings.",
    version="1.0.0"
)

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    # Start the background expiry task scheduler
    asyncio.create_task(scheduler.start_scheduler())

# ----------------- AUTH ENDPOINTS -----------------

@app.post("/api/auth/register", response_model=schemas.UserResponse, status_code=status.HTTP_201_CREATED)
def register(user_data: schemas.UserCreate, db: Session = Depends(get_db)):
    db.execute(text("BEGIN IMMEDIATE"))
    try:
        existing = db.query(models.User).filter(models.User.email == user_data.email).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email already registered")
            
        hashed_pwd = auth.get_password_hash(user_data.password)
        db_user = models.User(
            email=user_data.email,
            hashed_password=hashed_pwd,
            role=user_data.role
        )
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        return db_user
    except Exception as e:
        db.rollback()
        raise e

@app.post("/api/auth/login", response_model=schemas.Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    if not user or not auth.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = auth.create_access_token(
        data={"sub": user.email, "role": user.role, "user_id": user.id}
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/api/auth/me", response_model=schemas.UserResponse)
def get_me(current_user: models.User = Depends(auth.get_current_user)):
    return current_user


# ----------------- ADMIN ENDPOINTS -----------------

@app.post("/api/admin/venues", response_model=schemas.VenueResponse, status_code=status.HTTP_201_CREATED)
def create_venue(
    venue_data: schemas.VenueCreate,
    db: Session = Depends(get_db),
    admin_user: models.User = Depends(auth.require_admin)
):
    db.execute(text("BEGIN IMMEDIATE"))
    try:
        # Check if venue already exists by name
        existing = db.query(models.Venue).filter(models.Venue.name == venue_data.name).first()
        if existing:
            raise HTTPException(status_code=400, detail="Venue with this name already exists")
            
        layout = venue_data.layout
        total_seats = len(layout.rows) * layout.seats_per_row
        
        db_venue = models.Venue(
            name=venue_data.name,
            address=venue_data.address,
            total_seats=total_seats,
            layout=json.dumps(layout.dict())
        )
        db.add(db_venue)
        db.flush()  # to get db_venue.id
        
        # Populate seats
        for row in layout.rows:
            category = layout.category_map.get(row, "Standard")
            for num in range(1, layout.seats_per_row + 1):
                seat = models.Seat(
                    venue_id=db_venue.id,
                    row_name=row,
                    seat_number=num,
                    category=category
                )
                db.add(seat)
                
        db.commit()
        db.refresh(db_venue)
        return db_venue
    except Exception as e:
        db.rollback()
        raise e

@app.get("/api/admin/venues", response_model=List[schemas.VenueResponse])
def get_venues(db: Session = Depends(get_db), admin_user: models.User = Depends(auth.require_admin)):
    return db.query(models.Venue).all()


# ----------------- ORGANISER ENDPOINTS -----------------

@app.post("/api/organiser/events", response_model=schemas.EventResponse, status_code=status.HTTP_201_CREATED)
def create_event(
    event_data: schemas.EventCreate,
    db: Session = Depends(get_db),
    organiser_user: models.User = Depends(auth.require_organiser)
):
    db.execute(text("BEGIN IMMEDIATE"))
    try:
        venue = db.query(models.Venue).filter(models.Venue.id == event_data.venue_id).first()
        if not venue:
            raise HTTPException(status_code=404, detail="Venue not found")
            
        # Verify pricing categories match layout
        layout_dict = json.loads(venue.layout)
        categories_in_layout = set(layout_dict.get("category_map", {}).values())
        pricing_keys = set(event_data.pricing.keys())
        
        if not pricing_keys.issubset(pricing_keys): # checks pricing matches
            raise HTTPException(status_code=400, detail="Pricing must cover categories present in layout")
            
        db_event = models.Event(
            title=event_data.title,
            description=event_data.description,
            date=event_data.date,
            time=event_data.time,
            venue_id=event_data.venue_id,
            organiser_id=organiser_user.id,
            pricing=json.dumps(event_data.pricing)
        )
        db.add(db_event)
        db.flush()
        
        # Populate Event Seats status map
        seats = db.query(models.Seat).filter(models.Seat.venue_id == event_data.venue_id).all()
        for seat in seats:
            db_event_seat = models.EventSeat(
                event_id=db_event.id,
                seat_id=seat.id,
                status="available"
            )
            db.add(db_event_seat)
            
        db.commit()
        db.refresh(db_event)
        return db_event
    except Exception as e:
        db.rollback()
        raise e

@app.get("/api/organiser/events", response_model=List[schemas.EventResponse])
def get_organiser_events(
    db: Session = Depends(get_db),
    organiser_user: models.User = Depends(auth.require_organiser)
):
    # Admins see all events, organisers see their own
    if organiser_user.role == "admin":
        return db.query(models.Event).all()
    return db.query(models.Event).filter(models.Event.organiser_id == organiser_user.id).all()

@app.get("/api/organiser/events/{event_id}/summary", response_model=schemas.EventRevenueSummary)
def get_event_summary(
    event_id: int,
    db: Session = Depends(get_db),
    organiser_user: models.User = Depends(auth.require_organiser)
):
    event = db.query(models.Event).filter(models.Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
        
    if organiser_user.role != "admin" and event.organiser_id != organiser_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to access summary for this event")
        
    # Bookings stats
    bookings = db.query(models.Booking).filter(models.Booking.event_id == event_id).all()
    total_bookings = sum(1 for b in bookings if b.status == "confirmed")
    cancelled_bookings = sum(1 for b in bookings if b.status == "cancelled")
    total_revenue = sum(b.price_paid for b in bookings if b.status == "confirmed")
    
    # Waitlist count
    waitlist_count = db.query(models.Waitlist).filter(
        models.Waitlist.event_id == event_id,
        models.Waitlist.status == "waiting"
    ).count()
    
    return {
        "event_id": event.id,
        "title": event.title,
        "date": event.date,
        "time": event.time,
        "total_bookings": total_bookings,
        "cancelled_bookings": cancelled_bookings,
        "total_revenue": total_revenue,
        "waitlist_count": waitlist_count
    }


# ----------------- CUSTOMER ENDPOINTS -----------------

@app.get("/api/events", response_model=List[schemas.EventResponse])
def get_events(title: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(models.Event)
    if title:
        query = query.filter(models.Event.title.ilike(f"%{title}%"))
    return query.all()

@app.get("/api/events/{event_id}", response_model=schemas.EventResponse)
def get_event_details(event_id: int, db: Session = Depends(get_db)):
    event = db.query(models.Event).filter(models.Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event

@app.get("/api/events/{event_id}/seats", response_model=List[schemas.EventSeatResponse])
def get_event_seats(event_id: int, db: Session = Depends(get_db)):
    event_seats = (
        db.query(models.EventSeat)
        .join(models.Seat)
        .filter(models.EventSeat.event_id == event_id)
        .all()
    )
    
    # Filter expired holds in memory or database before returning (for quick cleanup)
    now = datetime.utcnow()
    seats_list = []
    for es in event_seats:
        status_val = es.status
        expires = es.expires_at
        
        # If hold expired, display as available
        if status_val == "held" and expires and expires < now:
            status_val = "available"
            expires = None
            
        seats_list.append({
            "seat_id": es.seat_id,
            "row_name": es.seat.row_name,
            "seat_number": es.seat.seat_number,
            "category": es.seat.category,
            "status": status_val,
            "expires_at": expires
        })
        
    return seats_list

@app.post("/api/events/{event_id}/hold", response_model=List[schemas.EventSeatResponse])
async def hold_event_seats(
    event_id: int,
    request: schemas.HoldSeatsRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    try:
        held_seats = await booking_service.hold_seats(db, current_user.id, event_id, request.seat_ids)
        return [
            {
                "seat_id": es.seat_id,
                "row_name": es.seat.row_name,
                "seat_number": es.seat.seat_number,
                "category": es.seat.category,
                "status": es.status,
                "expires_at": es.expires_at
            }
            for es in held_seats
        ]
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/events/{event_id}/book")
async def book_event_seats(
    event_id: int,
    request: schemas.HoldSeatsRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    try:
        booking_ref = await booking_service.confirm_booking(db, current_user.id, event_id, request.seat_ids)
        return {"booking_reference": booking_ref, "message": "Booking successful! Confirmation email has been sent."}
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/events/{event_id}/release")
async def release_event_seats(
    event_id: int,
    request: schemas.HoldSeatsRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    try:
        await booking_service.release_seats(db, current_user.id, event_id, request.seat_ids)
        return {"message": "Seats released successfully."}
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/events/{event_id}/waitlist", response_model=schemas.WaitlistResponse)
def join_event_waitlist(
    event_id: int,
    request: schemas.WaitlistCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    return booking_service.join_waitlist(db, current_user.id, event_id, request.seat_category)

@app.get("/api/customer/active-offers")
def get_active_offers(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    now = datetime.utcnow()
    # Find any pending, unexpired offer for this user
    offer = (
        db.query(models.Offer)
        .join(models.Waitlist)
        .filter(
            models.Waitlist.user_id == current_user.id,
            models.Offer.status == "pending",
            models.Offer.expires_at >= now
        )
        .first()
    )
    if not offer:
        return None
        
    return {
        "id": offer.id,
        "event_title": offer.waitlist.event.title,
        "seat_desc": f"{offer.seat.row_name}{offer.seat.seat_number}",
        "seat_category": offer.seat.category,
        "expires_at": offer.expires_at,
        "price": json.loads(offer.waitlist.event.pricing).get(offer.seat.category, 0.0)
    }

@app.get("/api/customer/bookings")
def get_customer_bookings(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    # Retrieve all user's bookings grouped by reference
    bookings = (
        db.query(models.Booking)
        .filter(models.Booking.user_id == current_user.id)
        .order_by(models.Booking.created_at.desc())
        .all()
    )
    
    # Group bookings by reference
    grouped = {}
    for bk in bookings:
        ref = bk.booking_reference
        if ref not in grouped:
            grouped[ref] = {
                "booking_reference": ref,
                "event_title": bk.event.title,
                "event_date": bk.event.date,
                "event_time": bk.event.time,
                "status": bk.status,
                "created_at": bk.created_at,
                "price_paid": 0.0,
                "seats": []
            }
        grouped[ref]["seats"].append(f"{bk.seat.row_name}{bk.seat.seat_number} ({bk.seat.category})")
        grouped[ref]["price_paid"] += bk.price_paid
        
    return list(grouped.values())

@app.post("/api/bookings/{booking_ref}/cancel")
async def cancel_customer_booking(
    booking_ref: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    try:
        await booking_service.cancel_booking(db, current_user.id, booking_ref)
        return {"message": "Booking successfully cancelled. Seats have been reallocated or released."}
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/offers/{offer_id}")
def get_offer_details(
    offer_id: int,
    db: Session = Depends(get_db)
):
    offer = db.query(models.Offer).filter(models.Offer.id == offer_id).first()
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
        
    now = datetime.utcnow()
    if offer.status != "pending" or offer.expires_at < now:
        return {
            "id": offer.id,
            "status": "expired" if offer.status == "pending" else offer.status,
            "expired": True
        }
        
    return {
        "id": offer.id,
        "event_title": offer.waitlist.event.title,
        "seat_desc": f"{offer.seat.row_name}{offer.seat.seat_number}",
        "seat_category": offer.seat.category,
        "expires_at": offer.expires_at,
        "price": json.loads(offer.waitlist.event.pricing).get(offer.seat.category, 0.0),
        "status": offer.status,
        "expired": False
    }

@app.post("/api/offers/{offer_id}/claim")
async def claim_waitlist_seat_offer(
    offer_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    try:
        booking_ref = await booking_service.claim_waitlist_offer(db, current_user.id, offer_id)
        return {"booking_reference": booking_ref, "message": "Waitlist claim successful! Ticket has been confirmed."}
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ----------------- REAL-TIME WEBSOCKET -----------------

@app.websocket("/api/ws/events/{event_id}")
async def websocket_endpoint(websocket: WebSocket, event_id: int):
    await manager.connect(event_id, websocket)
    try:
        while True:
            # We keep the connection alive by waiting for messages (e.g. heartbeat)
            # or just letting the socket listen.
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(event_id, websocket)
    except Exception:
        manager.disconnect(event_id, websocket)


# ----------------- STATIC SPA SERVING -----------------

# Set up static file mounting for frontend SPA
# Ensure frontend directory exists
os.makedirs("frontend", exist_ok=True)
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
