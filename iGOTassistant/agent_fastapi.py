
"""
Agent service implementation for the Karmayogi Bharat chatbot.
"""

# import uuid
import logging
import os
import sys
import time

import opik
from dotenv import load_dotenv
# import google.auth
# import google.generativeai as genai
from google.adk import Agent
from google.adk import Runner
from google.adk.artifacts import InMemoryArtifactService
from google.adk.events import Event, EventActions
from google.adk.sessions import DatabaseSessionService
from google.genai import types
from opik.integrations.adk import OpikTracer

# from .config.config import KB_BASE_URL, LLM_CONFIG, GOOGLE_AGENT
from .config.config import LLM_CONFIG, GOOGLE_AGENT
from .models.chat import Request
from .prompt import INSTRUCTION, GLOBAL_INSTRUCTION
from .tools.cert_tools import (
    handle_issued_certificate_issues,
    list_pending_contents,
    handle_certificate_qr_issues,
    handle_certificate_name_issues,
)
# from .tools.faq_tools import answer_general_questions
from .tools.faq_tools import (
    answer_general_questions,
    initialize_environment,
    initialize_knowledge_base
)
from .tools.otp_auth_tools import send_otp, verify_otp, check_channel
from .tools.tools import (
    # answer_general_questions,
    update_phone_number_tool,
)
from .tools.userinfo_tools import validate_user, load_details_for_registered_users, update_name
from .tools.zoho_ticket_tools import create_support_ticket_tool

# from fronend.streamlit_chat import cookie
# from .libs.storage import GCPStorage
# from .libs.bhashini import (DhruvaSpeechProcessor,
#                             DhruvaTranslator,
#                             LanguageCodes,
#                             convert_to_wav_with_ffmpeg)
# from .models.callbacks import before_tool
# from .tools.userinfo_tools import validate_user
# from .tools.tools import (
#     # validate_user,
#     load_details_for_registered_users,
#     answer_general_questions,
#     create_support_ticket_tool,
#     handle_certificate_issues,
#     verify_otp,
#     send_otp,
#     update_phone_number_tool,
#     list_pending_contents
# )

# from uvicorn.config import LOGGING_CONFIG
# import logging.config

import coloredlogs

# logging.basicConfig(
#     level=logging.INFO,
#     format="%(asctime)s : %(filename)s : %(funcName)s : %(levelname)s : %(message)s",
#     datefmt="%Y-%m-%d %H:%M:%S",
# )

# logging.config.dictConfig(LOGGING_CONFIG)

logger = logging.getLogger(__name__)
level_style = dict(
    coloredlogs.DEFAULT_FIELD_STYLES
)

coloredlogs.DEFAULT_FIELD_STYLES["levelname"] = dict(color='green', bold=True)
coloredlogs.install(
    level='INFO',
    fmt="%(asctime)s : %(filename)s : %(funcName)s : %(levelname)s : %(message)s")

logging.info("-"*100)

# speech_processor = DhruvaSpeechProcessor()
# translator = DhruvaTranslator()
# storage = GCPStorage()

opik.configure(url=os.getenv("OPIK_URL"), use_local=True)
opik_tracer = OpikTracer(project_name=os.getenv("OPIK_PROJECT"))


def initialize_env():
    """trying laod env before agent starts"""
    try:
        initialize_environment()
        KB_AUTH_TOKEN = os.getenv('KB_AUTH_TOKEN')
        KB_DIR = initialize_knowledge_base()
        response = answer_general_questions("What is karma points?")
        logging.info(response)
        logging.info("Knowledge base initialized successfully.")
    except (ValueError, FileNotFoundError, ImportError, RuntimeError) as e:
        logging.info("Error initializing knowledge base: %s", e)
        sys.exit(1)

    logging.info("✅ Successfully initialized tools and knowledge base")

initialize_env()


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

    
        logging.info("Initializing Google ADK agent")
        self.agent = Agent(
            model=os.getenv("GEMINI_MODEL"),
            name="iGOTAssistant",
            generate_content_config=LLM_CONFIG,
            instruction=INSTRUCTION,
            global_instruction=GLOBAL_INSTRUCTION,
            tools=[
                check_channel,
                validate_user,
                load_details_for_registered_users,
                answer_general_questions,
                create_support_ticket_tool,
                handle_issued_certificate_issues,
                send_otp,
                verify_otp,
                update_phone_number_tool,
                list_pending_contents,
                handle_certificate_name_issues,
                handle_certificate_qr_issues,
                update_name,
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

    async def start_new_session(self, user_id, request: Request) -> dict:
        """Start a new chat session with initial instructions."""
        logging.info(f'{user_id} :: Trying to start new session {request.session_id}')
        if not GOOGLE_AGENT:
            chat = self.agent.start_chat(
                history=[{
                    "role": "user",
                    "parts": [GLOBAL_INSTRUCTION, INSTRUCTION]
                }],
                enable_automatic_function_calling=True
            )
            # session_id = request.channel_id + "_" + request.session_id
            session_id = request.session_id
            self.chat_sessions[session_id] = {
                "chat": chat,
                "history": []
            }
            logging.info(f"{user_id} :: New session started : %s", session_id)
        else:
            if await self.session_service.get_session(app_name=self.app_name, session_id=request.session_id, user_id=user_id):
                return {"message" : "Session exist, try chat send."}

            logging.info(f'{user_id} :: Session id', request.session_id)
            self.user_id = user_id,
            self.session = await self.session_service.create_session(
                    app_name=self.app_name,
                    session_id=request.session_id ,
                    user_id=user_id
                    )
            # print(self.session.app_name, self.session.session_id, self.session.__user_id)
            # self.runner = Runner(app_name=self.app_name, agent=self.llm, session_service=self.session_service, artifact_service=self.artifact_service)
            # print('Generated session ', self.session.session_id, self.session.user_id)

        return {"message": "Starting new chat session."}

    async def send_message(self,user_id, request: Request) -> dict:
        """Send a message in an existing chat session."""
        response = ""
        audio_url = None

        content = types.Content(
            role='user',
            parts=[types.Part.from_text(text=request.text)]
        )

        # print('* user : ', content.model_dump(exclude_none=True))
        # print('-'*40)
        # print(request, self.session, self.user_id)
        # session_id = request.channel_id + "_" + request.session_id

        if not await self.runner.session_service.get_session(app_name=self.app_name, user_id=user_id, session_id=request.session_id):
            await self.start_new_session(user_id, request)

        # If the user is on the web channel, mark them as authenticated in the session context
        if request.channel_id == "web":
            # You may need to adjust how context is set depending on your ADK version
            session = await self.runner.session_service.get_session(
                app_name=self.app_name, user_id=user_id, session_id=request.session_id
            )

            if session is not None and not session.state.get("web", False):
                logging.info(f"{user_id} :: Setting the WEB ......")
                time_now = time.time()
                state_changes = {
                    "web" : True,
                    "user_id" : user_id,
                    "validuser" : True,
                    "otp_auth": True
                }

                action_with_update = EventActions(state_delta=state_changes)
                system_event = Event(
                    invocation_id="inv_login_update",
                    author="iGOTAssistant", # Or 'agent', 'tool' etc.
                    actions=action_with_update,
                    timestamp=time_now,
                )

                await self.runner.session_service.append_event(session, system_event)

            logging.info(f'{user_id} :: Setting state', session.state.get("web"))
            logging.info(f'{user_id} :: Setting user_id', session.state.get("user_id"))

        # print(self.session.id, self.session.user_id)
        try:
            # if not await self.runner.session_service.get_session(app_name=self.app_name, user_id=user_id, session_id=request.session_id):
            #     await self.start_new_session(user_id, request)

            async for event in self.runner.run_async(
                    # user_id=self.user_id,
                    user_id=user_id,
                    # user_id=request.user_id,
                    # session_id=request.session_id,
                    session_id=request.session_id,
                    new_message=content):
                # print(event)
                if event.content.parts and event.content.parts[0].text:
                    logging.info(f"{user_id} :: {event.author} : {event.content.parts[0].text}")
                    response = event.content.parts[0].text
        except Exception as e:
            logging.info(str(e))

        return {"text": response, "audio": audio_url}
