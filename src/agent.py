"""
Agent service implementation for the Karmayogi Bharat chatbot.
"""

import os
import google.auth
import google.generativeai as genai
from dotenv import load_dotenv

from .models.chat import StartChat
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

    def start_new_session(self, request: StartChat) -> dict:
        """Start a new chat session with initial instructions."""
        chat = self.llm_model.start_chat(
            history=[{
                "role": "user",
                "parts": [GLOBAL_INSTRUCTION, INSTRUCTION]
            }],
            enable_automatic_function_calling=True
        )

        session_id = request.channel_id + "_" + request.session_id
        self.chat_sessions[session_id] = {
            "chat": chat,
            "history": []
        }
        return {"message": "Starting new chat session."}

    def send_message(self, request: StartChat) -> dict:
        """Send a message in an existing chat session."""
        session_id = request.channel_id + "_" + request.session_id
        if session_id not in self.chat_sessions:
            self.start_new_session(request)

        session_data = self.chat_sessions[session_id]
        chat = session_data["chat"]
        history = session_data["history"]

        response = chat.send_message(request.text)
        content = response.text

        # Update chat history
        history.append({"role": "user", "parts": [request.text]})
        history.append({"role": "model", "parts": [content]})

        return {"response": content}
