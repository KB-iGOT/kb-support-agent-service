"""
This script implements a FastAPI-based server for a chatbot application
designed to assist users of the Karmayogi Bharat portal. The chatbot 
integrates with various APIs and tools to provide support for user queries,
including validating user registration, fetching user details,
handling certificate issues, and answering general questions 
based on a knowledge base.

Modules and Libraries:
- `re`, `json`: For regular expressions and JSON handling.
- `typing`: For type annotations.
- `urllib.parse`: For URL encoding.
- `llama_index`: For knowledge base indexing and querying.
- `fastapi`: For building the REST API.
- `pydantic`: For request validation.
- `dotenv`: For loading environment variables.
- `google.auth` and `google.generativeai`: For Google API integrations.
- `requests`: For making HTTP requests.

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
from pydantic import BaseModel
from dotenv import load_dotenv


import google.auth
import google.generativeai as genai

from tools.tools import (
    validate_email,
    load_details_for_registered_users,
    answer_general_questions,
    handle_certificate_issues
)

load_dotenv()

GEMINI_CRED = os.getenv("GEMINI_CRED")
KB_DIR = os.getenv("KB_DIR")
BEARER = os.getenv("BEARER")
GEMINI_MODEL = os.getenv("GEMINI_MODEL")

credentials, project = google.auth.load_credentials_from_file(GEMINI_CRED)

chat_sessions = {}

class StartChat(BaseModel):
    """
    Model for starting a chat session.
    """
    sessionid : str
    text : str


class Message(BaseModel):
    """
    Model for sending a message in a chat session.
    """
    sessionid : str
    text : str


genai.configure(credentials=credentials)
configs = {
    'temperature' : 1,
    'top_p' : 0.9,
    'top_k' : 40,
    'max_output_tokens' : 4096,
    'response_mime_type' : 'text/plain'

}

llmmodel = genai.GenerativeModel(model_name=GEMINI_MODEL,
                                generation_config=configs,
                                tools=[
                                    validate_email,
                                    load_details_for_registered_users,
                                    answer_general_questions,
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
        system_prompt = """You are smart Karmayogi Bharat Support agent.
            Please follow following instruction while having conversations with user.
            1. Be truthful, don't make things up
            2. Be clear, consise and provide simpler solution
            3. Don't disclose any user information that is crucial for a user.
            4. Before every conversation make sure of users authority.
            5. Don't answer other questions like jokes, trivia, news other than our Karmayogi Bharat related details.
            6. Follow safety guardrails.
            7. Don't talk about implementation details about tools available.
            8. You can show details about the user enrollments if user is authenticated and show only when asked.
            9. Make sure to take help of tools wherever possible before answering. 
            follow chat template below; as chat flowchart
            Greet user creatively and ask if user is a registered user?
                Case 1: yes, Please share your registered emailId or Phone number?
                Case 2: No, How may I help you?
 
                Case 1:
                    Case 1-1: if user shares registered emailId or phone, fetch user profile info and user Course Enrollment Info. reply saying "Found your details. Please let me know your query. Use tool for loading enrollment details, make a tool call to `load_details_for_registered_user`. Make sure to call this tool everytime after validating email"
                    Case 1-2: if user enters wrong input, reply "Sorry, seems like the information provided is either invalid or not found in our registry. Please let me know your query.".
 
                Case1-1:
                    Case1-1-1: user says "I did not get my certificate".
                        - [Assistance] please let me know the course name
                        - [user] enters course name
                        - [system] checks if user is enrolled in the course records. 
                            - [system] if yes, check if the user's progress is 100. also, check if user has got/issued certificate or not.
                                - [system] if 'completionPercentage' is 100 and 'issuedCertificates' does not exists, invoke 'issueCertificate' API.trigger a support mail mentioning the details of user and course with a defined format.
                                - [system] if 'completionPercentage' is less than 100, check 'contentStatus' object to fetch all the content ids (do_ids) not in status '2' ( complete state). fetch all of these name of contents using 'contentSearch' API.
                                - [Assistance] You haven't completed all the course contents, following contents are yet to be completed: content 1, conten2 ...
                        - [Assistance]if no, tell user that you haven't enrolled in course mentioned, enrol and finish all the contents to get a certificate.
                        
                Case 2:
                    Answer the question from general FAQ vector database, for general queries use answer_general_questions tool.
                        
                """

        chat = llmmodel.start_chat(history=[{"role": "user", "parts": [system_prompt]}],
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
            raise HTTPException(status_code=404,
                                detail={"message" : "Session id not found"})

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
