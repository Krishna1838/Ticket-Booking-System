import os
import qrcode
import smtplib
import base64
import json
import urllib.request
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

# Mail spool folder path in the project workspace
SPOOL_DIR = "C:/Users/vardh/.gemini/antigravity/scratch/ticket-booking-system/mail_spool"
EMAILS_DIR = os.path.join(SPOOL_DIR, "emails")
QRCODES_DIR = os.path.join(SPOOL_DIR, "qrcodes")

os.makedirs(EMAILS_DIR, exist_ok=True)
os.makedirs(QRCODES_DIR, exist_ok=True)

# Load .env file manually if it exists to populate os.environ
env_path = "C:/Users/vardh/.gemini/antigravity/scratch/ticket-booking-system/.env"
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                # Strip potential surrounding quotes from values
                val_cleaned = val.strip().strip('"').strip("'")
                os.environ[key.strip()] = val_cleaned

# Load SMTP configurations from environment variables
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = os.getenv("SMTP_PORT")
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")

def generate_qr_code(booking_ref: str) -> str:
    """
    Generates a QR code containing the booking reference.
    Saves it to mail_spool/qrcodes and returns the file path.
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(booking_ref)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    qr_filename = f"{booking_ref}.png"
    qr_filepath = os.path.join(QRCODES_DIR, qr_filename)
    img.save(qr_filepath)
    return qr_filepath

def send_email_via_resend(recipient_email: str, subject: str, html_body: str, qr_filepath: str = None) -> bool:
    """
    Sends an email via Resend's HTTPS API (bypassing SMTP cloud blocks).
    """
    resend_key = os.getenv("RESEND_API_KEY")
    if not resend_key:
        return False
        
    try:
        url = "https://api.resend.com/emails"
        
              # Force onboarding@resend.dev for Resend sandbox testing if SENDER_EMAIL is a public domain (like Gmail)
        sender = "onboarding@resend.dev"
        if SENDER_EMAIL and not any(d in SENDER_EMAIL.lower() for d in ["@gmail.com", "@yahoo.com", "@outlook.com", "@hotmail.com"]):
            sender = SENDER_EMAIL
            
        payload = {
            "from": f"Ticket Booking <{sender}>",
            "to": [recipient_email],
            "subject": subject,
            "html": html_body
        }
        
        # If QR code is provided, encode it in base64 and attach it inline
        if qr_filepath and os.path.exists(qr_filepath):
            with open(qr_filepath, "rb") as f:
                img_base64 = base64.b64encode(f.read()).decode("utf-8")
            payload["attachments"] = [
                {
                    "filename": "qrcode.png",
                    "content": img_base64,
                    "id": "qrcode"
                }
            ]
            
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {resend_key}",
                "Content-Type": "application/json"
            },
            method="POST"
        )
        
        with urllib.request.urlopen(req) as response:
            response.read()
            print(f"\n[RESEND API EMAIL SENT] To: {recipient_email}")
            return True
            
    except Exception as e:
        print(f"\n[RESEND API ERROR] Failed to send email via Resend API: {e}")
        return False

def send_email_via_smtp(recipient_email: str, subject: str, html_body: str, qr_filepath: str = None) -> bool:
    """
    Sends an email using standard SMTP. Returns True if successful, False otherwise.
    If RESEND_API_KEY is set, routes the request through the Resend Web API instead.
    """
    resend_key = os.getenv("RESEND_API_KEY")
    if resend_key:
        return send_email_via_resend(recipient_email, subject, html_body, qr_filepath)
        
    if not SMTP_HOST:
        return False
        
    try:
        port = int(SMTP_PORT) if SMTP_PORT else 587
        sender = SENDER_EMAIL or SMTP_USER
        
        # Create message container
        msg = MIMEMultipart("related")
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = recipient_email
        
        # Attach the HTML body
        msg_html = MIMEText(html_body, "html")
        msg.attach(msg_html)
        
        # If a QR code image is provided, attach it inline matching the <img src="cid:qrcode"> tag
        if qr_filepath and os.path.exists(qr_filepath):
            with open(qr_filepath, "rb") as f:
                img_data = f.read()
                msg_image = MIMEImage(img_data)
                msg_image.add_header("Content-ID", "<qrcode>")
                msg.attach(msg_image)
                
        # Connect using SSL (port 465) or STARTTLS (port 587 / other ports)
        if port == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, port, timeout=5) as server:
                if SMTP_USER and SMTP_PASSWORD:
                    server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(sender, recipient_email, msg.as_string())
        else:
            with smtplib.SMTP(SMTP_HOST, port, timeout=5) as server:
                server.starttls()
                if SMTP_USER and SMTP_PASSWORD:
                    server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(sender, recipient_email, msg.as_string())
            
        print(f"\n[LIVE EMAIL SENT] To: {recipient_email}")
        print(f"Subject: {subject}\n")
        return True
    except Exception as e:
        print(f"\n[LIVE EMAIL ERROR] Failed to send email to {recipient_email} via SMTP: {e}")
        print("Falling back to local offline spooling...\n")
        return False

def send_booking_confirmation(
    recipient_email: str,
    booking_ref: str,
    event_title: str,
    date: str,
    time: str,
    seats: list[str],  # E.g. ["Row A - Seat 3", "Row A - Seat 4"]
    price: float
):
    """
    Sends a booking confirmation email with a generated QR code ticket.
    Uses SMTP if credentials exist, otherwise falls back to saving locally as an HTML file.
    """
    qr_filepath = generate_qr_code(booking_ref)
    subject = f"Booking Confirmed: {event_title} [Ref: {booking_ref}]"
    
    # Check if SMTP is configured to decide image source format
    is_live = bool(SMTP_HOST)
    img_src = "cid:qrcode" if is_live else os.path.relpath(qr_filepath, EMAILS_DIR).replace("\\", "/")
    
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{subject}</title>
    <style>
        body {{ font-family: Arial, sans-serif; color: #333; margin: 20px; }}
        .card {{ border: 1px solid #ddd; border-radius: 8px; padding: 20px; max-width: 500px; background-color: #fafafa; }}
        .header {{ border-bottom: 2px solid #5850ec; padding-bottom: 10px; margin-bottom: 20px; }}
        .qr-code {{ margin: 20px 0; text-align: center; }}
        .qr-code img {{ border: 1px solid #ccc; border-radius: 4px; width: 200px; height: 200px; }}
        .details {{ line-height: 1.6; }}
        .footer {{ margin-top: 25px; font-size: 12px; color: #777; border-top: 1px solid #eee; padding-top: 10px; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="header">
            <h2 style="margin: 0; color: #5850ec;">Ticket Confirmation</h2>
            <p style="margin: 5px 0 0 0; color: #555;">Thank you for your booking!</p>
        </div>
        <div class="details">
            <p><strong>Booking Ref:</strong> {booking_ref}</p>
            <p><strong>Event:</strong> {event_title}</p>
            <p><strong>Date & Time:</strong> {date} at {time}</p>
            <p><strong>Seats:</strong> {', '.join(seats)}</p>
            <p><strong>Total Paid:</strong> ${price:.2f}</p>
        </div>
        <div class="qr-code">
            <p><strong>Scan Your QR Ticket:</strong></p>
            <img src="{img_src}" alt="Ticket QR Code">
        </div>
        <div class="footer">
            <p>Please present this QR code at the venue entrance. Enjoy your event!</p>
        </div>
    </div>
</body>
</html>
"""
    
    # Try sending via live SMTP
    sent_successfully = send_email_via_smtp(recipient_email, subject, html_content, qr_filepath)
    
    # Fallback to local spooling if not live or if sending failed
    if not sent_successfully:
        email_filename = f"booking_{booking_ref}.html"
        email_filepath = os.path.join(EMAILS_DIR, email_filename)
        with open(email_filepath, "w", encoding="utf-8") as f:
            f.write(html_content)

        print(f"\n[EMAIL SPOOLED] To: {recipient_email}")
        print(f"Subject: {subject}")
        print(f"Saved email file: {email_filepath}")
        print(f"Generated QR code: {qr_filepath}\n")

def send_waitlist_offer(
    recipient_email: str,
    offer_id: int,
    event_title: str,
    seat_category: str,
    seats: list[str],
    expires_at: datetime
):
    """
    Sends a waitlist offer notification with a claim link.
    Uses SMTP if credentials exist, otherwise falls back to saving locally as an HTML file.
    """
    expires_str = expires_at.strftime("%Y-%m-%d %H:%M:%S UTC")
    
    # Time limited claim url
    claim_url = f"http://localhost:8000/#claim-offer?offer_id={offer_id}"
    subject = f"Waitlist Seat Available: {event_title}!"
    
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{subject}</title>
    <style>
        body {{ font-family: Arial, sans-serif; color: #333; margin: 20px; }}
        .card {{ border: 1px solid #ddd; border-radius: 8px; padding: 20px; max-width: 500px; background-color: #fffbeb; border-left: 5px solid #d97706; }}
        .header {{ border-bottom: 2px solid #d97706; padding-bottom: 10px; margin-bottom: 20px; }}
        .details {{ line-height: 1.6; }}
        .btn {{ display: inline-block; padding: 10px 20px; background-color: #d97706; color: white; text-decoration: none; border-radius: 5px; font-weight: bold; margin-top: 15px; }}
        .btn:hover {{ background-color: #b45309; }}
        .footer {{ margin-top: 25px; font-size: 12px; color: #777; border-top: 1px solid #eee; padding-top: 10px; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="header">
            <h2 style="margin: 0; color: #d97706;">Seat Available from Waitlist!</h2>
            <p style="margin: 5px 0 0 0; color: #555;">Good news! A seat has freed up for you.</p>
        </div>
        <div class="details">
            <p><strong>Event:</strong> {event_title}</p>
            <p><strong>Category:</strong> {seat_category}</p>
            <p><strong>Available Seats:</strong> {', '.join(seats)}</p>
            <p style="color: #b45309;"><strong>Offer Expiration:</strong> {expires_str} (You have 10 minutes to claim this seat!)</p>
            <p>To secure your booking, click the button below to purchase your ticket:</p>
            <a href="{claim_url}" class="btn">Complete Booking Now</a>
        </div>
        <div class="footer">
            <p>If you do not complete the booking before the expiration, the offer will automatically lapse and the seat will be offered to the next person in line.</p>
        </div>
    </div>
</body>
</html>
"""
    
    # Try sending via live SMTP
    sent_successfully = send_email_via_smtp(recipient_email, subject, html_content)
    
    # Fallback to local spooling if not live or if sending failed
    if not sent_successfully:
        email_filename = f"offer_{offer_id}.html"
        email_filepath = os.path.join(EMAILS_DIR, email_filename)
        with open(email_filepath, "w", encoding="utf-8") as f:
            f.write(html_content)

        print(f"\n[EMAIL SPOOLED] To: {recipient_email}")
        print(f"Subject: {subject}")
        print(f"Claim Link: {claim_url}")
        print(f"Saved email file: {email_filepath}\n")
