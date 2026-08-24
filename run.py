import os
import uvicorn

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8000))
    reload = os.getenv("RELOAD", "false").lower() == "true"
    
    print("Starting Ticket Booking System...")
    print(f"Serving at: http://{host}:{port}")
    print(f"API Documentation (Swagger UI) at: http://{host}:{port}/docs")
    uvicorn.run("backend.main:app", host=host, port=port, reload=reload)
