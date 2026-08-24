from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from backend.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, nullable=False)  # admin, organiser, customer
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    events = relationship("Event", back_populates="organiser")
    bookings = relationship("Booking", back_populates="user")
    waitlists = relationship("Waitlist", back_populates="user")


class Venue(Base):
    __tablename__ = "venues"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    address = Column(String, nullable=False)
    total_seats = Column(Integer, nullable=False)
    layout = Column(String, nullable=False)  # JSON representation of layout (rows, cols, category maps)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    seats = relationship("Seat", back_populates="venue", cascade="all, delete-orphan")
    events = relationship("Event", back_populates="venue")


class Seat(Base):
    __tablename__ = "seats"

    id = Column(Integer, primary_key=True, index=True)
    venue_id = Column(Integer, ForeignKey("venues.id", ondelete="CASCADE"), nullable=False)
    row_name = Column(String, nullable=False)
    seat_number = Column(Integer, nullable=False)
    category = Column(String, nullable=False)  # Premium, Standard

    # Relationships
    venue = relationship("Venue", back_populates="seats")
    event_seats = relationship("EventSeat", back_populates="seat", cascade="all, delete-orphan")
    bookings = relationship("Booking", back_populates="seat")

    __table_args__ = (
        UniqueConstraint("venue_id", "row_name", "seat_number", name="uq_venue_row_seat"),
    )


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)
    date = Column(String, nullable=False)  # YYYY-MM-DD
    time = Column(String, nullable=False)  # HH:MM
    venue_id = Column(Integer, ForeignKey("venues.id"), nullable=False)
    organiser_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    pricing = Column(String, nullable=False)  # JSON pricing: {"Premium": 150.0, "Standard": 80.0}
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    venue = relationship("Venue", back_populates="events")
    organiser = relationship("User", back_populates="events")
    event_seats = relationship("EventSeat", back_populates="event", cascade="all, delete-orphan")
    bookings = relationship("Booking", back_populates="event")
    waitlists = relationship("Waitlist", back_populates="event")


class EventSeat(Base):
    __tablename__ = "event_seats"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    seat_id = Column(Integer, ForeignKey("seats.id", ondelete="CASCADE"), nullable=False)
    status = Column(String, default="available")  # available, held, booked
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # user who has the active hold or booking
    expires_at = Column(DateTime, nullable=True)  # timestamp when hold expires

    # Relationships
    event = relationship("Event", back_populates="event_seats")
    seat = relationship("Seat", back_populates="event_seats")

    __table_args__ = (
        UniqueConstraint("event_id", "seat_id", name="uq_event_seat"),
    )


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    seat_id = Column(Integer, ForeignKey("seats.id"), nullable=False)
    booking_reference = Column(String, index=True, nullable=False)
    price_paid = Column(Float, nullable=False)
    status = Column(String, default="confirmed")  # confirmed, cancelled
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="bookings")
    event = relationship("Event", back_populates="bookings")
    seat = relationship("Seat", back_populates="bookings")


class Waitlist(Base):
    __tablename__ = "waitlist"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    seat_category = Column(String, nullable=False)  # Premium, Standard
    status = Column(String, default="waiting")  # waiting, offered, expired, booked
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="waitlists")
    event = relationship("Event", back_populates="waitlists")
    offers = relationship("Offer", back_populates="waitlist", cascade="all, delete-orphan")


class Offer(Base):
    __tablename__ = "offers"

    id = Column(Integer, primary_key=True, index=True)
    waitlist_id = Column(Integer, ForeignKey("waitlist.id", ondelete="CASCADE"), nullable=False)
    seat_id = Column(Integer, ForeignKey("seats.id"), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    status = Column(String, default="pending")  # pending, completed, expired
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    waitlist = relationship("Waitlist", back_populates="offers")
    seat = relationship("Seat")
