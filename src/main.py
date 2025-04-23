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

from fastapi import FastAPI
from .routes.chat import router as chat_router

app = FastAPI(
    title="Karmayogi Bharat Chat API",
    description="API for the Karmayogi Bharat chatbot service",
    version="1.0.0"
)

@app.get("/")
async def root():
    """Root endpoint to verify server status."""
    return {"message": "This is Karmayogi Bharat chat agent REST integration !!"}

# Include the chat routes
app.include_router(chat_router)
