import threading
import time
import json
import logging
from fastapi import HTTPException
from backend import models, booking_service, auth
from backend.database import Base, engine, SessionLocal

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(threadName)s] %(levelname)s: %(message)s")
logger = logging.getLogger("ConcurrencyTest")

# Shared state to record results
results = []

def run_hold_seat(user_id: int, event_id: int, seat_id: int, thread_name: str):
    """
    Worker function to attempt holding a seat.
    """
    logger.info(f"Thread {thread_name} attempting to hold seat {seat_id} for user {user_id}...")
    db = SessionLocal()
    try:
        # Import asyncio to call async hold_seats in a synchronous thread loop
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Execute hold_seats
        start_time = time.time()
        loop.run_until_complete(booking_service.hold_seats(db, user_id, event_id, [seat_id]))
        end_time = time.time()
        
        logger.info(f"Thread {thread_name} SUCCESSFULLY held seat in {end_time - start_time:.4f}s")
        results.append({
            "thread": thread_name,
            "user_id": user_id,
            "status": "SUCCESS",
            "error": None
        })
    except HTTPException as he:
        logger.warning(f"Thread {thread_name} FAILED to hold seat: {he.detail} (HTTP {he.status_code})")
        results.append({
            "thread": thread_name,
            "user_id": user_id,
            "status": "FAILED",
            "error": f"HTTP {he.status_code}: {he.detail}"
        })
    except Exception as e:
        logger.error(f"Thread {thread_name} encountered error: {e}")
        results.append({
            "thread": thread_name,
            "user_id": user_id,
            "status": "ERROR",
            "error": str(e)
        })
    finally:
        db.close()

def main():
    logger.info("Initializing concurrency test database...")
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    
    # 1. Clean up existing test data
    db.query(models.Booking).delete()
    db.query(models.EventSeat).delete()
    db.query(models.Seat).delete()
    db.query(models.Event).delete()
    db.query(models.Venue).delete()
    db.query(models.User).delete()
    db.commit()
    
    # 2. Setup seed data
    # Create test customers
    pwd_hash = auth.get_password_hash("password123")
    user1 = models.User(email="cust1@test.com", hashed_password=pwd_hash, role="customer")
    user2 = models.User(email="cust2@test.com", hashed_password=pwd_hash, role="customer")
    organiser = models.User(email="org@test.com", hashed_password=pwd_hash, role="organiser")
    db.add_all([user1, user2, organiser])
    db.flush()
    
    # Create test venue
    layout_data = {
        "rows": ["A"],
        "seats_per_row": 2,
        "category_map": {"A": "Standard"}
    }
    venue = models.Venue(
        name="Concurrency Hall",
        address="123 Test St",
        total_seats=2,
        layout=json.dumps(layout_data)
    )
    db.add(venue)
    db.flush()
    
    # Generate seats
    seat1 = models.Seat(venue_id=venue.id, row_name="A", seat_number=1, category="Standard")
    seat2 = models.Seat(venue_id=venue.id, row_name="A", seat_number=2, category="Standard")
    db.add_all([seat1, seat2])
    db.flush()
    
    # Create test event
    event = models.Event(
        title="Concurrent Show",
        date="2026-10-10",
        time="18:00",
        venue_id=venue.id,
        organiser_id=organiser.id,
        pricing=json.dumps({"Standard": 50.0})
    )
    db.add(event)
    db.flush()
    
    # Generate event seat status maps
    es1 = models.EventSeat(event_id=event.id, seat_id=seat1.id, status="available")
    es2 = models.EventSeat(event_id=event.id, seat_id=seat2.id, status="available")
    db.add_all([es1, es2])
    db.commit()
    
    user1_id = user1.id
    user2_id = user2.id
    event_id = event.id
    target_seat_id = seat1.id
    
    db.close()
    
    logger.info("Seed data ready. Spawning 2 concurrent threads targeting Seat A-1...")
    
    t1 = threading.Thread(target=run_hold_seat, args=(user1_id, event_id, target_seat_id, "User1-Thread"), name="User1-Thread")
    t2 = threading.Thread(target=run_hold_seat, args=(user2_id, event_id, target_seat_id, "User2-Thread"), name="User2-Thread")
    
    # Start threads almost simultaneously
    t1.start()
    t2.start()
    
    # Wait for completion
    t1.join()
    t2.join()
    
    # Print Test Report
    print("\n" + "="*50)
    print("CONCURRENCY TEST REPORT")
    print("="*50)
    print(f"Target Seat ID: {target_seat_id} (Row A - Seat 1)")
    print(f"Total Requests: {len(results)}")
    
    successes = [r for r in results if r["status"] == "SUCCESS"]
    failures = [r for r in results if r["status"] == "FAILED"]
    errors = [r for r in results if r["status"] == "ERROR"]
    
    print(f"Successes: {len(successes)}")
    print(f"Failures (409 Conflict expected): {len(failures)}")
    print(f"Errors: {len(errors)}")
    
    print("\nDetails:")
    for r in results:
        err_msg = f" - Reason: {r['error']}" if r['error'] else ""
        print(f"- {r['thread']}: {r['status']}{err_msg}")
        
    print("="*50)
    
    # Assert conditions for passing test
    assert len(successes) == 1, f"Expected exactly 1 successful hold, got {len(successes)}"
    assert len(failures) == 1, f"Expected exactly 1 conflict failure, got {len(failures)}"
    print("TEST PASSED: Concurrency protection successfully prevented double-holding.")
    print("="*50 + "\n")

if __name__ == "__main__":
    main()
