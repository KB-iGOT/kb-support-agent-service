"""
This script implements a FastAPI-based server for a chatbot application
designed to assist users of the Karmayogi Bharat portal. The chatbot 
integrates with various APIs and tools to provide support for user queries,
including validating user registration, fetching user details,
handling certificate issues, and answering general questions 
based on a knowledge base.

Key Features:
1. **Knowledge Base Integration**:
    - Loads documents from a directory and creates a query engine
      using `llama_index`.
2. **User Validation**:
    - Validates user email addresses against the Karmayogi Bharat portal.
    - Fetches user details and enrollment information for registered users.
3. **Certificate Management**:
    - Handles certificate issuance for completed courses.
    - Identifies incomplete course components and provides feedback to users.
4. **General Query Handling**:
    - Answers general questions using a vector-based knowledge base.
5. **Chat Session Management**:
    - Supports starting and continuing chat sessions with a conversational model.
    - Maintains chat history for each session.

6. **API Endpoints**:
    - `/`: Root endpoint to verify server status.
    - `/chat/start`: Starts a new chat session.
    - `/chat/send`: Continues an existing chat session.
7. **Safety and Guardrails**:
    - Implements safety guidelines to ensure accurate and secure responses.
    - Avoids disclosing sensitive user information.
Usage:
- Run the server using `uvicorn main:app --reload`.
- Interact with the chatbot via the provided REST API endpoints.
Note:
- Ensure that the required environment variables and API keys are properly configured.
- Replace hardcoded tokens and sensitive information with secure configurations before deployment.
Main chat application server file.

"""

import os

from fastapi import FastAPI, HTTPException
from dotenv import load_dotenv

import google.auth
import google.generativeai as genai

from .models.chat import StartChat, Message
from .config.config import LLM_CONFIG
from .models.prompt import INSTRUCTION, GLOBAL_INSTRUCTION

from .tools.tools import (
    validate_email,
    load_details_for_registered_users,
    answer_general_questions,
    create_support_ticket_tool,
    handle_certificate_issues
)

load_dotenv()

GEMINI_CRED = os.getenv("GEMINI_CRED")
KB_DIR = os.getenv("KB_DIR")
BEARER = os.getenv("BEARER")
GEMINI_MODEL = os.getenv("GEMINI_MODEL")

credentials, project = google.auth.load_credentials_from_file(GEMINI_CRED)

chat_sessions = {}


genai.configure(credentials=credentials)

llmmodel = genai.GenerativeModel(model_name=GEMINI_MODEL,
                                generation_config=LLM_CONFIG,
                                tools=[
                                    validate_email,
                                    load_details_for_registered_users,
                                    answer_general_questions,
                                    create_support_ticket_tool,
                                    handle_certificate_issues])


app = FastAPI()

@app.get("/")
async def root():
    """
    Root endpoint to verify server status.
    """
    return {"message" : "This is Karmayogi Bharat chat agent REST integration !!"}


@app.post("/chat/start")
async def start_chat(request : StartChat):
    """
    Endpoint to start a new chat session.
    """
    try:
        chat = llmmodel.start_chat(history=[
            {
                "role": "user",
                "parts": [GLOBAL_INSTRUCTION, INSTRUCTION]
            }
            ],
            enable_automatic_function_calling=True)

        chat_sessions[request.sessionid] = {"chat": chat, "history" : []}
        return { "message" : "Starting new chat session."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/chat/send")
async def continue_chat(request : Message):
    """
    Endpoint to continue an existing chat session.
    """
    try:
        if request.sessionid not in chat_sessions:
            return {"response" : "Session id not found, please start a new session."}
            # raise HTTPException(status_code=404,
                                # detail={"message" : "Session id not found"})

        session_data = chat_sessions[request.sessionid]
        chat = session_data["chat"]
        history = session_data["history"]

        response = chat.send_message(request.text)
        content = response.text

        # Update chat history
        history.append({"role": "user", "parts": [request.text]})
        history.append({"role": "model", "parts": [content]})

        return {"response": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
