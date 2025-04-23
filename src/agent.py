"""
Agent service implementation for the Karmayogi Bharat chatbot.
"""

import os
import google.auth
import google.generativeai as genai
from dotenv import load_dotenv

from .config.config import LLM_CONFIG
from .prompt import INSTRUCTION, GLOBAL_INSTRUCTION
from .tools.tools import (
    validate_email,
    load_details_for_registered_users,
    answer_general_questions,
    create_support_ticket_tool,
    handle_certificate_issues
)

class ChatAgent:
    """
    ChatAgent class to manage chat sessions and interactions with the Gemini model.
    """
    def __init__(self):
        load_dotenv()
        self.chat_sessions = {}

        # Initialize Gemini
        credentials, _ = google.auth.load_credentials_from_file(
            os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))
        genai.configure(credentials=credentials)

        self.llm_model = genai.GenerativeModel(
            model_name=os.getenv("GEMINI_MODEL"),
            generation_config=LLM_CONFIG,
            tools=[
                validate_email,
                load_details_for_registered_users,
                answer_general_questions,
                create_support_ticket_tool,
                handle_certificate_issues
            ]
        )

    def start_new_session(self, session_id: str) -> dict:
        """Start a new chat session with initial instructions."""
        chat = self.llm_model.start_chat(
            history=[{
                "role": "user",
                "parts": [GLOBAL_INSTRUCTION, INSTRUCTION]
            }],
            enable_automatic_function_calling=True
        )

        self.chat_sessions[session_id] = {
            "chat": chat,
            "history": []
        }
        return {"message": "Starting new chat session."}

    def send_message(self, session_id: str, message: str) -> dict:
        """Send a message in an existing chat session."""
        if session_id not in self.chat_sessions:
            return {"response": "Session id not found, please start a new session."}

        session_data = self.chat_sessions[session_id]
        chat = session_data["chat"]
        history = session_data["history"]

        response = chat.send_message(message)
        content = response.text

        # Update chat history
        history.append({"role": "user", "parts": [message]})
        history.append({"role": "model", "parts": [content]})

        return {"response": content}
