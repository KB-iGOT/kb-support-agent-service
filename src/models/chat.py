""" pydantic models for chat functionality """
from pydantic import BaseModel

class StartChat(BaseModel):
    """
    Model for starting a chat session.
    """
    channel_id : str
    session_id : str
    text : str
    audio : str
    language: str


class Message(BaseModel):
    """
    Model for sending a message in a chat session.
    """
    sessionid : str
    text : str
