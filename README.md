# ShowPass: Ticket Booking System

A real-time ticket booking platform for movies and concerts. Customers can book seats from a visual map, holds are auto-released on checkout abandonment via a background scheduler, sold-out seat categories support a First-In-First-Out (FIFO) waitlist with automated offer flows on cancellations, and confirmed bookings produce an email with a QR code ticket.

---

## Technical Stack
* **Backend**: FastAPI (Python 3.13)
* **Frontend**: Single Page Application (HTML5, Vanilla JS, Tailwind CSS via CDN)
* **Database**: SQLite (SQLAlchemy ORM) with Write-Ahead Logging (WAL) and serialization locks
* **Real-time**: WebSockets for live seat map updates
* **Emails**: Local HTML file spooling under `mail_spool/emails/` with embedded QR codes

---

## Setup & Running Guide

### 1. Prerequisites
Ensure you have **Python 3.10+** installed on your system.

### 2. Installation
Clone or extract the project files and navigate to the project directory:
```bash
cd ticket-booking-system
```

Create a virtual environment and install the required dependencies:
```bash
# Create virtual environment
python -m venv .venv

# Activate virtual environment (Windows)
.venv\Scripts\activate

# Install requirements
pip install -r requirements.txt
```

### 3. Run the Application
Execute the startup script:
```bash
python run.py
```
* **Frontend**: Open `http://localhost:8000` in your web browser.
* **API Documentation (Swagger UI)**: Access `http://localhost:8000/docs`.

### 4. Running the Concurrency Test
We provide an automated multi-threaded script that simulates concurrent customers attempting to hold the exact same seat at the same time:
```bash
python test_concurrency.py
```
This script initializes a test database, generates seeds, spawns parallel threads, and verifies that SQLite serialisation locks prevent double-booking.

---

## Database Schema

We use 8 tables to implement the complete business flow:

### 1. `users`
* `id` (INTEGER, PK)
* `email` (VARCHAR, Unique, Index)
* `hashed_password` (VARCHAR)
* `role` (VARCHAR) - `'admin'`, `'organiser'`, or `'customer'`
* `created_at` (DATETIME)

### 2. `venues`
* `id` (INTEGER, PK)
* `name` (VARCHAR)
* `address` (VARCHAR)
* `total_seats` (INTEGER)
* `layout` (VARCHAR) - JSON representation of row/columns and seat category mappings
* `created_at` (DATETIME)

### 3. `seats`
* `id` (INTEGER, PK)
* `venue_id` (INTEGER, FK -> `venues.id`)
* `row_name` (VARCHAR)
* `seat_number` (INTEGER)
* `category` (VARCHAR) - `'Premium'` or `'Standard'`
* *Constraint*: Unique index on `(venue_id, row_name, seat_number)`

### 4. `events`
* `id` (INTEGER, PK)
* `title` (VARCHAR)
* `description` (VARCHAR, Nullable)
* `date` (VARCHAR) - `YYYY-MM-DD`
* `time` (VARCHAR) - `HH:MM`
* `venue_id` (INTEGER, FK -> `venues.id`)
* `organiser_id` (INTEGER, FK -> `users.id`)
* `pricing` (VARCHAR) - JSON map of category prices (e.g. `{"Premium": 150.0, "Standard": 75.0}`)
* `created_at` (DATETIME)

### 5. `event_seats` (Real-time seat state map per event instance)
* `id` (INTEGER, PK)
* `event_id` (INTEGER, FK -> `events.id`)
* `seat_id` (INTEGER, FK -> `seats.id`)
* `status` (VARCHAR) - `'available'`, `'held'`, or `'booked'`
* `user_id` (INTEGER, FK -> `users.id`, Nullable) - user who has the active hold or booking
* `expires_at` (DATETIME, Nullable) - hold expiration timestamp
* *Constraint*: Unique index on `(event_id, seat_id)`

### 6. `bookings`
* `id` (INTEGER, PK)
* `user_id` (INTEGER, FK -> `users.id`)
* `event_id` (INTEGER, FK -> `events.id`)
* `seat_id` (INTEGER, FK -> `seats.id`)
* `booking_reference` (VARCHAR, Unique, Index)
* `price_paid` (FLOAT)
* `status` (VARCHAR) - `'confirmed'` or `'cancelled'`
* `created_at` (DATETIME)

### 7. `waitlist` (FIFO Waitlist Queue)
* `id` (INTEGER, PK)
* `user_id` (INTEGER, FK -> `users.id`)
* `event_id` (INTEGER, FK -> `events.id`)
* `seat_category` (VARCHAR) - `'Premium'` or `'Standard'`
* `status` (VARCHAR) - `'waiting'`, `'offered'`, `'expired'`, or `'booked'`
* `created_at` (DATETIME)

### 8. `offers` (Time-limited waitlist offers)
* `id` (INTEGER, PK)
* `waitlist_id` (INTEGER, FK -> `waitlist.id`)
* `seat_id` (INTEGER, FK -> `seats.id`)
* `expires_at` (DATETIME)
* `status` (VARCHAR) - `'pending'`, `'completed'`, or `'expired'`
* `created_at` (DATETIME)

---

## API Documentation

### 1. Authentication
* `POST /api/auth/register`: Create user account.
  * Request Body: `{ "email": "user@test.com", "password": "password", "role": "customer" }`
* `POST /api/auth/login`: Authenticate and receive JWT.
  * Request Body: Form-data `username` and `password`.
  * Response: `{ "access_token": "token...", "token_type": "bearer" }`
* `GET /api/auth/me`: Retrieve current user details (Bearer header required).

### 2. Admin Tasks
* `POST /api/admin/venues`: Add venue and automatically generate seats.
  * Request Body:
    ```json
    {
      "name": "Apollo Hall",
      "address": "456 Concert Ave",
      "layout": {
        "rows": ["A", "B", "C"],
        "seats_per_row": 8,
        "category_map": { "A": "Premium", "B": "Standard", "C": "Standard" }
      }
    }
    ```
* `GET /api/admin/venues`: List all configured venues.

### 3. Organiser Tasks
* `POST /api/organiser/events`: Publish new event (automatically links venue seats).
  * Request Body:
    ```json
    {
      "title": "Rock Concert",
      "description": "Live rock concert",
      "date": "2026-09-15",
      "time": "20:00",
      "venue_id": 1,
      "pricing": { "Premium": 200.0, "Standard": 100.0 }
    }
    ```
* `GET /api/organiser/events`: List organiser's published events.
* `GET /api/organiser/events/{event_id}/summary`: Revenue and booking analytics for an event.

### 4. Customer & Booking Operations
* `GET /api/events`: Retrieve all events (optional query parameter `?title=xxx`).
* `GET /api/events/{event_id}/seats`: Retrieve seat status mapping.
* `POST /api/events/{event_id}/hold`: Place a 10-minute hold on seats.
  * Request Body: `{ "seat_ids": [1, 2] }`
* `POST /api/events/{event_id}/book`: Confirm purchase for held seats.
  * Request Body: `{ "seat_ids": [1, 2] }`
* `POST /api/events/{event_id}/waitlist`: Join waitlist for a sold-out category.
  * Request Body: `{ "seat_category": "Premium" }`
* `GET /api/customer/bookings`: Booking history list.
* `POST /api/bookings/{booking_ref}/cancel`: Cancel booking (triggers waitlist).
* `GET /api/offers/{offer_id}`: Fetch details for a waitlist offer.
* `POST /api/offers/{offer_id}/claim`: Claim waitlist offer and purchase ticket.

### 5. WebSockets
* `WS /api/ws/events/{event_id}`: Real-time seat update stream. Broadcasts updates like:
  ```json
  {
    "type": "seat_update",
    "seats": [
      { "seat_id": 1, "row_name": "A", "seat_number": 1, "category": "Premium", "status": "held", "expires_at": "..." }
    ]
  }
  ```

---

## Core Logic Explanation

### 1. Seat Hold and Concurrency Lock
* **Transactions**: We wrap seat holds in SQL transactions starting with `BEGIN IMMEDIATE` to serialise writes at the database level.
* **Validation**: We query the seat status. If any seat is booked or has a valid hold (`status == 'held'` and `expires_at >= current_time`), the transaction aborts with a `409 Conflict`.
* **State Transition**: If valid, seats are marked `'held'` with an `expires_at` 10 minutes from now.

### 2. Waitlist FIFO Allocation
* **Trigger**: A seat release (hold expiry or booking cancellation) triggers waitlist processing.
* **Lookup**: The system queries the `waitlist` table for the oldest entry (`created_at ASC`) with status `'waiting'` for that category and event.
* **State Transition**:
  - The waitlist status becomes `'offered'`.
  - The seat is re-held for the waitlist user for 10 minutes.
  - A record is added to the `offers` table.
  - A notification email with a claim link is generated.
* **Lapse**: If the claim expires, the scheduler marks the offer/waitlist as `'expired'`, and automatically re-runs the waitlist query for the next person in line.
