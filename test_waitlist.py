import time
import json
import logging
from datetime import datetime
from sqlalchemy import text
from backend import models, booking_service, auth
from backend.database import Base, engine, SessionLocal

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("WaitlistTest")

def main():
    logger.info("Initializing waitlist test database...")
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    
    # 1. Clean up existing test data
    db.query(models.Offer).delete()
    db.query(models.Booking).delete()
    db.query(models.EventSeat).delete()
    db.query(models.Waitlist).delete()
    db.query(models.Event).delete()
    db.query(models.Seat).delete()
    db.query(models.Venue).delete()
    db.query(models.User).delete()
    db.commit()
    
    # 2. Seed data
    pwd_hash = auth.get_password_hash("password123")
    user1 = models.User(email="cust1@test.com", hashed_password=pwd_hash, role="customer")
    user2 = models.User(email="cust2@test.com", hashed_password=pwd_hash, role="customer")
    organiser = models.User(email="org@test.com", hashed_password=pwd_hash, role="organiser")
    db.add_all([user1, user2, organiser])
    db.flush()
    
    # Create venue with 1 seat (easy to sell out)
    layout_data = {
        "rows": ["A"],
        "seats_per_row": 1,
        "category_map": {"A": "Standard"}
    }
    venue = models.Venue(
        name="Waitlist Theatre",
        address="321 Queue Blvd",
        total_seats=1,
        layout=json.dumps(layout_data)
    )
    db.add(venue)
    db.flush()
    
    seat1 = models.Seat(venue_id=venue.id, row_name="A", seat_number=1, category="Standard")
    db.add(seat1)
    db.flush()
    
    # Create event
    event = models.Event(
        title="Single Seat Show",
        date="2026-11-11",
        time="20:00",
        venue_id=venue.id,
        organiser_id=organiser.id,
        pricing=json.dumps({"Standard": 100.0})
    )
    db.add(event)
    db.flush()
    
    es1 = models.EventSeat(event_id=event.id, seat_id=seat1.id, status="available")
    db.add(es1)
    db.commit()
    
    # Keep track of IDs
    cust1_id = user1.id
    cust2_id = user2.id
    event_id = event.id
    seat_id = seat1.id
    
    logger.info("--- STARTING TEST FLOW ---")
    
    # Step A: Customer 1 holds the seat
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    logger.info("Step A: Customer 1 holds the only seat...")
    loop.run_until_complete(booking_service.hold_seats(db, cust1_id, event_id, [seat_id]))
    
    # Refresh and verify
    db.refresh(es1)
    logger.info(f"Seat status: {es1.status}, Held by: {es1.user_id}, Expires at: {es1.expires_at}")
    assert es1.status == "held" and es1.user_id == cust1_id
    
    # Step B: Customer 1 confirms booking
    logger.info("Step B: Customer 1 confirms purchase...")
    booking_ref = loop.run_until_complete(booking_service.confirm_booking(db, cust1_id, event_id, [seat_id]))
    db.refresh(es1)
    logger.info(f"Seat status: {es1.status}, Booked by: {es1.user_id}, Booking Ref: {booking_ref}")
    assert es1.status == "booked" and es1.user_id == cust1_id
    
    # Verify show is sold out
    is_sold_out = booking_service.check_category_sold_out(db, event_id, "Standard")
    logger.info(f"Is category 'Standard' sold out? {is_sold_out}")
    assert is_sold_out is True
    
    # Step C: Customer 2 joins the waitlist
    logger.info("Step C: Customer 2 joins the waitlist for 'Standard' category...")
    waitlist_entry = booking_service.join_waitlist(db, cust2_id, event_id, "Standard")
    logger.info(f"Waitlist Entry ID: {waitlist_entry.id}, Status: {waitlist_entry.status}, Created at: {waitlist_entry.created_at}")
    assert waitlist_entry.status == "waiting" and waitlist_entry.user_id == cust2_id
    
    # Step D: Customer 1 cancels their booking
    logger.info("Step D: Customer 1 cancels their booking. This should trigger direct auto-booking promotion to Customer 2...")
    loop.run_until_complete(booking_service.cancel_booking(db, cust1_id, booking_ref))
    
    # Step E: Verify waitlist promotion database state
    db.refresh(es1)
    db.refresh(waitlist_entry)
    
    # Fetch Customer 2's booking details
    cust2_booking = db.query(models.Booking).filter(models.Booking.user_id == cust2_id).first()
    
    logger.info("Step E: Verifying database state post-cancellation...")
    logger.info(f"Seat status: {es1.status}, Booked by: {es1.user_id}")
    logger.info(f"Customer 2 Waitlist status: {waitlist_entry.status}")
    logger.info(f"Customer 2 Booking created: {cust2_booking is not None}, Booking Ref: {cust2_booking.booking_reference if cust2_booking else 'N/A'}, Booking status: {cust2_booking.status if cust2_booking else 'N/A'}")
    
    assert es1.status == "booked", "Seat should be directly booked"
    assert es1.user_id == cust2_id, "Seat should be assigned to Customer 2"
    assert waitlist_entry.status == "booked", "Waitlist entry status should be updated to 'booked'"
    assert cust2_booking is not None and cust2_booking.status == "confirmed", "Booking should be confirmed directly"
    
    db.close()
    
    print("\n" + "="*50)
    print("WAITLIST AUTO-ASSIGNMENT (PREPAID) TEST REPORT")
    print("="*50)
    print("1. Seed data and sold out seat category: PASSED")
    print("2. Waitlist entry insertion on sold out (prepaid): PASSED")
    print("3. Ticket cancellation triggers direct promotion: PASSED")
    print("4. Seat auto-booked & assigned to waitlist user: PASSED")
    print("5. Confirmed booking record created directly: PASSED")
    print("="*50)
    print("TEST PASSED: Prepaid Waitlist auto-assignment is 100% correct!")
    print("="*50 + "\n")

if __name__ == "__main__":
    main()
