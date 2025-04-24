"""
Chat routes for the Karmayogi Bharat chatbot API.
"""

from fastapi import APIRouter, HTTPException
from ..models.chat import StartChat
from ..agent import ChatAgent

router = APIRouter(prefix="/chat", tags=["chat"])
agent = ChatAgent()

@router.get("/")
async def health_check():
    """Health check endpoint to verify chat service status."""
    return {"message": "Chat service is running"}

@router.post("/start")
async def start_chat(request: StartChat):
    """Endpoint to start a new chat session."""
    try:
        return agent.start_new_session(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

@router.post("/send")
async def continue_chat(request: StartChat):
    """Endpoint to continue an existing chat session."""
    try:
        return agent.send_message(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
