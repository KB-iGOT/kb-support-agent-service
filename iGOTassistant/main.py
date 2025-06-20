

"""
Agent service implementation for the Karmayogi Bharat chatbot.
"""

# import os
# import logging

# from dotenv import load_dotenv

# from google.adk import Agent

# # opik integration.
# from opik.integrations.adk import OpikTracer
# import opik
# from requests import session


# # from .models.callbacks import before_tool

# from .config.config import LLM_CONFIG
# from .prompt import INSTRUCTION, GLOBAL_INSTRUCTION
# from .tools.userinfo_tools import validate_user, load_details_for_registered_users, update_name
# from .tools.cert_tools import (
#         handle_issued_certificate_issues,
#         list_pending_contents,
#         handle_certificate_qr_issues,
#         handle_certificate_name_issues,
#         )
# from .tools.otp_auth_tools import send_otp, verify_otp
# from .tools.zoho_ticket_tools import create_support_ticket_tool
# from .tools.faq_tools import answer_general_questions
# from .tools.tools import (
#     # answer_general_questions,
#     update_phone_number_tool,
# )

# from fastapi import APIRouter, HTTPException

# logger = logging.getLogger(__name__)
# load_dotenv()

# opik.configure(url=os.getenv("OPIK_URL"), use_local=True)
# # opik.configure(url="https://kbagent-opik.uat.karmayogibharat.net/api")
# opik_tracer = OpikTracer(project_name=os.getenv("OPIK_PROJECT"))

# agent = Agent(
#     model=os.getenv("GEMINI_MODEL"),
#     name="iGotAssistant",
#     generate_content_config=LLM_CONFIG,
#     instruction=INSTRUCTION,
#     global_instruction=GLOBAL_INSTRUCTION,
#     tools=[
#         validate_user,
#         load_details_for_registered_users,
#         answer_general_questions,
#         create_support_ticket_tool,
#         handle_issued_certificate_issues,
#         send_otp,
#         verify_otp,
#         update_phone_number_tool,
#         update_name,
#         list_pending_contents,
#         handle_certificate_qr_issues,
#         handle_certificate_name_issues,
#     ],
#     before_agent_callback=opik_tracer.before_agent_callback,
#     after_agent_callback=opik_tracer.after_agent_callback,
#     before_model_callback=opik_tracer.before_model_callback,
#     after_model_callback=opik_tracer.after_model_callback,
#     before_tool_callback=opik_tracer.before_tool_callback,
#     after_tool_callback=opik_tracer.after_tool_callback,
#     # before_tool_callback=before_tool,
#     # before_tool_callback=before_tool,
#     # before_tool_callback=before_tool,
#     # before_tool_callback=before_tool,
#     # before_tool_callback=before_tool,
#     # before_tool_callback=before_tool,
# )

# from pydantic import BaseModel
# from google.adk.cli.fast_api import get_fast_api_app
# from google.adk.runners import Runner
# from fastapi.staticfiles import StaticFiles
# from google.adk.sessions import InMemorySessionService

# session_service = InMemorySessionService

# class ChatRequest(BaseModel):
#     text: str
#     user_id: str
#     session_id: str
#     app_name: str = "iGotAssistant"
#     cookie: str


# router = APIRouter()

# @router.get("/chat")
# async def chat(request: ChatRequest):
#     try:
#         runner = Runner(
#             app_name=request.app_name,
#             agent=agent,
#             session_service=session_service,
#         )

#         events = [ event 
#                   async for event in runner.run_async(
#                       user_id=request.user_id,
#                       session_id=request.session_id,
#                       new_message=request.text,
#                   )]
#         return events
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

# app = get_fast_api_app(agents_dir=".", web=True)

# app.include_router(router)
# ANGULAR_DIST_PATH = "../browser"
# app.mount("/dev-ui", StaticFiles(directory=ANGULAR_DIST_PATH, html=True), name="static")


# print('Starting the Server')

import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
# import uvicorn

from .routes.chat import router as chat_router
from .utils import logs

# adding loggers comment files if you don't want logs to be added in files
logger = logging.getLogger(__name__)

# current logs load on console as well as files
# logs.log_to_stdio()
# logs.log_to_folder()

# logger.info("Loading Server.")

app = FastAPI(
    title="Karmayogi Bharat Chat API",
    description="API for the Karmayogi Bharat chatbot service",
    version="1.0.0",
    debug=True
)

# app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)


# print('Starting the app.')
@app.get("/")
async def root():
    """Root endpoint to verify server status."""
    return {"message": "This is Karmayogi Bharat chat agent REST integration !!"}

# print('/ is loaded')
# Include the chat routes
app.include_router(chat_router)

# if __name__ == "__main__":
    #uvicorn.run('main:app', host="127.0.0.1", port=5000, log_level="info", reload=True, debug=True)

