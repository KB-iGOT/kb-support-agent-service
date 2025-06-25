

"""
Agent service implementation for the Karmayogi Bharat chatbot.
"""

import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routes.chat import router as chat_router
from .agent_fastapi import initialize_env

# adding loggers comment files if you don't want logs to be added in files
logger = logging.getLogger(__name__)

initialize_env()

app = FastAPI(
    title="Karmayogi Bharat Chat API",
    description="API for the Karmayogi Bharat chatbot service",
    version="1.0.0",
    debug=True
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)


@app.get("/")
async def root():
    """Root endpoint to verify server status."""
    return {"message": "This is Karmayogi Bharat chat agent REST integration !!"}

# Include the chat routes
app.include_router(chat_router)

