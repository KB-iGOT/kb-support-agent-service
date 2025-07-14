"""
Agent service implementation for the Karmayogi Bharat chatbot.
"""

import logging
import os
import sys
import time

import opik
import coloredlogs

from dotenv import load_dotenv
from google.adk import Agent
from google.adk import Runner
from google.adk.artifacts import InMemoryArtifactService
from google.adk.events import Event, EventActions
from google.adk.sessions import DatabaseSessionService
from google.genai import types
from opik.integrations.adk import OpikTracer
from google.adk.tools import FunctionTool, transfer_to_agent
from google.cloud import aiplatform
from google.adk.models.lite_llm import LiteLlm
import json



from .config.config import LLM_CONFIG
from .models.chat import Request
from .prompt import INSTRUCTION, GLOBAL_INSTRUCTION
from .tools.cert_tools import (
    handle_issued_certificate_issues,
    list_pending_contents,
    handle_certificate_qr_issues,
    handle_certificate_name_issues,
)
from .tools.faq_tools import (
    answer_general_questions,
    initialize_environment,
    initialize_knowledge_base
)
from .tools.otp_auth_tools import send_otp, verify_otp
from .tools.tools import (
    update_phone_number_tool,
    get_combined_user_details_tool,
    answer_course_event_questions
)
from .tools.userinfo_tools import fetch_userdetails, load_details_for_registered_users, update_name
from .tools.zoho_ticket_tools import create_support_ticket_tool


def configure_logging():
    coloredlogs.DEFAULT_FIELD_STYLES["levelname"] = dict(color='green', bold=True)
    coloredlogs.install(
        level='INFO',
        fmt="%(asctime)s : %(filename)s : %(funcName)s : %(levelname)s : %(message)s")

configure_logging()
logger = logging.getLogger("iGOT")

opik.configure(url=os.getenv("OPIK_URL"), use_local=True)
opik_tracer = OpikTracer(project_name=os.getenv("OPIK_PROJECT"))


def initialize_env():
    """trying laod env before agent starts"""
    try:
        initialize_environment()
        KB_AUTH_TOKEN = os.getenv('KB_AUTH_TOKEN')
        KB_DIR = initialize_knowledge_base()
        response = answer_general_questions("What is karma points?")
        logger.info(response)
    except (ValueError, FileNotFoundError, ImportError, RuntimeError) as e:
        logger.info("Error initializing knowledge base: %s", e)
        sys.exit(1)

    logger.info("✅ Successfully initialized tools and knowledge base")




# Note: CourseAgent has been replaced with answer_course_event_questions tool
# which uses Ollama directly to answer course and event questions using Redis user data

class ChatAgent:
    """
    ChatAgent class to manage chat sessions and interactions with the Gemini model.
    """
    app_name = "iGOTAssitant"
    agent = None
    user_id = None
    session_service = DatabaseSessionService(db_url=os.getenv("POSTGRES_URL"))
    artifact_service = InMemoryArtifactService()
    runner = None
    session = None

    def __init__(self):
        load_dotenv()
        self.chat_sessions = {}

    
        logger.info("Initializing Google ADK agent")
        self.agent = Agent(
            model=os.getenv("GEMINI_MODEL"),
            description="You are a helpful assistant that can answer learning platform related conversations.",
            # model=LiteLlm(os.getenv("OLLAMA_MODEL")),
            name="iGOTAssistant",
            generate_content_config=LLM_CONFIG,
            instruction=INSTRUCTION,
            # include_contents='none',
            global_instruction=GLOBAL_INSTRUCTION,
            tools=[
                FunctionTool(get_combined_user_details_tool),
                # FunctionTool(fetch_userdetails),
                # FunctionTool(load_details_for_registered_users),
                FunctionTool(answer_general_questions),
                FunctionTool(answer_course_event_questions),
                FunctionTool(create_support_ticket_tool),
                FunctionTool(handle_issued_certificate_issues),
                FunctionTool(send_otp),
                FunctionTool(verify_otp),
                FunctionTool(update_phone_number_tool),
                FunctionTool(list_pending_contents),
                FunctionTool(handle_certificate_name_issues),
                FunctionTool(handle_certificate_qr_issues),
                FunctionTool(update_name),
                # FunctionTool(generate_with_vertex_cache)
                transfer_to_agent,
            ],
            before_agent_callback=opik_tracer.before_agent_callback,
            after_agent_callback=opik_tracer.after_agent_callback,
            before_model_callback=opik_tracer.before_model_callback,
            after_model_callback=opik_tracer.after_model_callback,
            before_tool_callback=opik_tracer.before_tool_callback,
            after_tool_callback=opik_tracer.after_tool_callback,
        )

        self.runner = Runner(app_name=self.app_name, 
                            agent=self.agent, session_service=self.session_service,
                            artifact_service=self.artifact_service)
        logger.info("ChatAgent initialized")

    async def start_new_session(self, user_id, session_id: str) -> dict:
        """Start a new chat session with initial instructions."""
        # logger.info(f'{user_id} :: Trying to start new session {request.session_id}')

        if await self.session_service.get_session(app_name=self.app_name, session_id=session_id, user_id=user_id):
            return {"message" : "Session exist, try chat send."}

        # logger.info(f'{user_id} :: Session id', request.session_id)
        self.user_id = user_id,
        self.session = await self.session_service.create_session(
                app_name=self.app_name,
                session_id=session_id ,
                user_id=user_id
                )

        return {"message": "Starting new chat session."}

    async def send_message(self, user_id, request: Request, session_id: str) -> dict:
        """Send a message in an existing chat session."""
        response = ""
        audio_url = None
        # MAX_CONTEXT_EVENTS = 5

        if not request.text:
            raise ValueError("Request text cannot be empty.")
        
        content = types.Content(
            role='user',
            parts=[types.Part.from_text(text=request.text)]
        )


        if not await self.runner.session_service.get_session(app_name=self.app_name, user_id=user_id, session_id=session_id):
            await self.start_new_session(user_id, session_id)

        # If the user is on the web channel, mark them as authenticated in the session context
        if request.channel_id == "web" or request.channel_id == "app": 
            # You may need to adjust how context is set depending on your ADK version
            session = await self.runner.session_service.get_session(
                app_name=self.app_name, user_id=user_id, session_id=session_id
            )

        

            if session is not None and not session.state.get("web", False):
                logger.info(f"{user_id} :: Setting the WEB ......")
                time_now = time.time()
                state_changes = {
                    "web" : True,
                    "user_id" : user_id,
                    "validuser" : True,
                    "otp_auth": True,
                    "loaded_details" : False
                }

                action_with_update = EventActions(state_delta=state_changes)
                system_event = Event(
                    invocation_id="inv_login_update",
                    author="iGOTAssistant", # Or 'agent', 'tool' etc.
                    actions=action_with_update,
                    timestamp=time_now,
                )

                await self.runner.session_service.append_event(session, system_event)

            # logger.info(f'{user_id} :: Setting state', session.state.get("web"))
            # logger.info(f'{user_id} :: Setting user_id', session.state.get("user_id"))

        try:
            async for event in self.runner.run_async(
                    user_id=user_id,
                    session_id=session_id,
                    new_message=content):
                if event.is_final_response():
                    response = event.content.parts[0].text
                # if event.content and getattr(event.content.parts[0], "function_call"):
                #     print(event.content.parts[0].function_call)
                if event.content:
                    print(event.content)
        except Exception as e:
            logger.info(str(e))

        if response == "": 
            return {"text": "Sorry, Something went wrong, try again later.", "audio": audio_url}
        return {"text": response, "audio": audio_url}

