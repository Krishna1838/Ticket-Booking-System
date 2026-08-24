# System Design Write-Up: Ticket Booking System

This document outlines the technical design for the core modules of the Ticket Booking System, focusing on seat holds, concurrency protection, and waitlist automation.

---

## 1. Seat Hold and TTL Mechanism
When a customer selects available seats on the visual map, the system places a temporary **hold** rather than booking them immediately. This ensures seats are temporarily reserved during the checkout process (preventing other customers from selecting them) without permanently locking them if the customer abandons the transaction.

### Data Model
The hold status is managed in the `event_seats` table, which bridges physical `seats` to a specific `event`.
* **Columns**: `status` (available, held, booked), `user_id` (current holder/booker), and `expires_at` (expiration timestamp).
* **Hold TTL**: Configured to 10 minutes. When a hold is successfully created, `status` becomes `held` and `expires_at` is set to `now() + 10 minutes`.

### Background Expiration Scheduler
A lightweight background loop (`scheduler.py`) runs every 5 seconds inside the FastAPI process.
1. It queries `event_seats` where `status == 'held'` and `expires_at < now()`.
2. For each expired seat, it initiates a transaction to:
   - Reset the seat status to `available` and clear `user_id`/`expires_at`.
   - Check if there are waitlisted users for the seat's category. If so, it triggers the **waitlist assignment flow** (described in Section 3).
   - If not, the seat is released back to the general public.
3. It broadcasts the seat status update to all active customers via WebSockets.

---

## 2. Concurrency Prevention
In high-demand ticket releases, thousands of customers might attempt to hold or book the same seat simultaneously. The system must guarantee that **no two users can hold or book the same seat**.

### Database-Level Isolation
To achieve strict correctness, we enforce serialised write operations using database transactions:
* **SQLite Immediate Transactions**: By default, SQLite has a single writer limit. We initiate write-intensive operations (holds, bookings, cancellations) using `BEGIN IMMEDIATE`. This instantly acquires a database write lock, putting concurrent write attempts into a queue (with a 30-second connection timeout). This prevents SQLite `busy` or `locked` exceptions while ensuring absolute serializability.
* **Atomic State Validation**: Within the transaction, the status of the requested seats is queried. If any seat has a status of `booked` or has an active hold (`status == 'held'` and `expires_at >= now()`), the transaction is aborted, and a `409 Conflict` is returned.
* **Database Constraints**: A unique composite index `uq_event_seat` on `event_seats(event_id, seat_id)` prevents duplicate status mapping rows.

---

## 3. Waitlist Auto-Assignment Flow
When a seat category is sold out (all seats are booked or actively held), customers can join a First-In-First-Out (FIFO) waitlist queue.

### Activation & Allocation
When a confirmed booking is cancelled, or when a hold expires:
1. The transaction cancels the booking (or hold) and sets the `event_seat` status to `available`.
2. A subsequent serialized sub-transaction checks the `waitlist` table for entries where `event_id == event_id`, `seat_category == seat_category`, and `status == 'waiting'`, sorted by `created_at ASC`.
3. If an applicant is found, the system:
   - Changes the waitlist status to `offered`.
   - Re-holds the seat for this user (`event_seats.status = 'held'`, `user_id = waitlist_user_id`, `expires_at = now() + 10 minutes`).
   - Creates a pending record in the `offers` table.
   - Spools a waitlist offer email containing a time-limited claim link.
4. If no waitlist applicant is found, the seat is left as `available` for the public.

---

## 4. Time-Limited Offer Handling
Waitlist offers represent a special class of holds. The waitlisted customer is granted a 10-minute window to purchase the offered seat.

### Claiming
The customer clicks the claim link (`/#claim-offer?offer_id=X`), which opens the Claim Offer view. Clicking "Purchase Seat Now" executes a transaction:
1. Verifies the offer is `pending`, the current time is before `expires_at`, and the user matches the waitlist owner.
2. Converts the hold to a permanent booking, marking the `Offer` as `completed` and the `Waitlist` entry as `booked`.
3. Spools the booking confirmation email with the ticket QR code.

### Expiry
If the customer fails to claim the offer in 10 minutes, the background scheduler detects the expired offer:
1. Marks `Offer` and `Waitlist` records as `expired`.
2. Resets the `event_seat` hold.
3. Automatically triggers `process_waitlist_assignment` for this seat, offering it to the next customer in the queue.
