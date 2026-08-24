import os
import sys
import uvicorn

# Ensure the root project directory is in Python search path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8000))
    reload = os.getenv("RELOAD", "false").lower() == "true"
    
    print("Starting Ticket Booking System...")
    print(f"Serving at: http://{host}:{port}")
    print(f"API Documentation (Swagger UI) at: http://{host}:{port}/docs")
    uvicorn.run("backend.main:app", host=host, port=port, reload=reload)
