from datetime import datetime
from typing import List, Optional, Dict
from pydantic import BaseModel, EmailStr, Field

# User Schemas
class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)
    role: str = Field(..., pattern="^(admin|organiser|customer)$")

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: int
    email: str
    role: str
    created_at: datetime

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: Optional[str] = None
    role: Optional[str] = None
    user_id: Optional[int] = None

# Venue Schemas
class VenueLayoutSeat(BaseModel):
    row: str
    number: int
    category: str

class VenueLayout(BaseModel):
    rows: List[str]
    seats_per_row: int
    category_map: Dict[str, str]  # e.g. {"A": "Premium", "B": "Premium", "C": "Standard"}

class VenueCreate(BaseModel):
    name: str
    address: str
    layout: VenueLayout

class VenueResponse(BaseModel):
    id: int
    name: str
    address: str
    total_seats: int
    layout: str  # JSON string
    created_at: datetime

    class Config:
        from_attributes = True

# Event Schemas
class EventCreate(BaseModel):
    title: str
    description: Optional[str] = None
    date: str  # YYYY-MM-DD
    time: str  # HH:MM
    venue_id: int
    pricing: Dict[str, float]  # e.g., {"Premium": 150.0, "Standard": 80.0}

class EventResponse(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    date: str
    time: str
    venue_id: int
    organiser_id: int
    pricing: str  # JSON string
    created_at: datetime

    class Config:
        from_attributes = True

# Seat and Seat Status Schemas
class SeatResponse(BaseModel):
    id: int
    row_name: str
    seat_number: int
    category: str

    class Config:
        from_attributes = True

class EventSeatResponse(BaseModel):
    seat_id: int
    row_name: str
    seat_number: int
    category: str
    status: str  # available, held, booked
    expires_at: Optional[datetime] = None

# Booking Schemas
class HoldSeatsRequest(BaseModel):
    seat_ids: List[int]

class BookingResponse(BaseModel):
    id: int
    booking_reference: str
    event_id: int
    seat_ids: List[int]
    price_paid: float
    status: str
    created_at: datetime

    class Config:
        from_attributes = True

# Waitlist Schemas
class WaitlistCreate(BaseModel):
    seat_category: str

class WaitlistResponse(BaseModel):
    id: int
    user_id: int
    event_id: int
    seat_category: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True

# Offer Schemas
class OfferResponse(BaseModel):
    id: int
    waitlist_id: int
    seat_id: int
    expires_at: datetime
    status: str
    created_at: datetime

    class Config:
        from_attributes = True

# Organiser Summary
class EventRevenueSummary(BaseModel):
    event_id: int
    title: str
    date: str
    time: str
    total_bookings: int
    cancelled_bookings: int
    total_revenue: float
    waitlist_count: int
