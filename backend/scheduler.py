import asyncio
import logging
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.orm import Session
from backend import models, booking_service
from backend.database import SessionLocal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def cleanup_expired_holds():
    """
    Checks for expired holds (both normal and waitlist offers),
    cancels them, and processes the next in line.
    """
    db: Session = SessionLocal()
    try:
        now = datetime.utcnow()
        # Find all event seats that are held and expired
        expired_seats = (
            db.query(models.EventSeat)
            .filter(models.EventSeat.status == "held", models.EventSeat.expires_at < now)
            .all()
        )
        
        if not expired_seats:
            return
            
        logger.info(f"Found {len(expired_seats)} expired holds to clean up.")
        
        for es in expired_seats:
            event_id = es.event_id
            seat_id = es.seat_id
            category = es.seat.category
            
            # Use SERIALIZED write transaction for this seat
            db.execute(text("BEGIN IMMEDIATE"))
            try:
                # Check if this seat expiration is related to a waitlist offer
                offer = (
                    db.query(models.Offer)
                    .filter(
                        models.Offer.seat_id == seat_id,
                        models.Offer.status == "pending"
                    )
                    .join(models.Waitlist)
                    .filter(models.Waitlist.event_id == event_id)
                    .first()
                )
                
                if offer:
                    logger.info(f"Expiring waitlist offer {offer.id} for seat {seat_id}.")
                    offer.status = "expired"
                    offer.waitlist.status = "expired"
                    
                # Reset the seat hold in the database
                es.status = "available"
                es.user_id = None
                es.expires_at = None
                
                db.commit()
                logger.info(f"Released expired hold on seat {es.seat.row_name}{es.seat.seat_number}.")
            except Exception as e:
                db.rollback()
                logger.error(f"Error releasing seat {seat_id} hold: {e}")
                continue
                
            # Trigger waitlist assignment for the freed seat
            db.execute(text("BEGIN IMMEDIATE"))
            try:
                await booking_service.process_waitlist_assignment(db, event_id, seat_id, category)
                db.commit()
            except Exception as e:
                db.rollback()
                logger.error(f"Error processing waitlist after expiry for seat {seat_id}: {e}")
                
    except Exception as e:
        logger.error(f"Scheduler cleanup loop encountered an error: {e}")
    finally:
        db.close()

async def start_scheduler():
    """
    Background loop that runs every 5 seconds.
    """
    logger.info("Background expiry scheduler started.")
    while True:
        try:
            await cleanup_expired_holds()
        except Exception as e:
            logger.error(f"Scheduler loop error: {e}")
        await asyncio.sleep(5)
