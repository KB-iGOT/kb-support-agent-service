
"""
Agent service implementation for the Karmayogi Bharat chatbot.
"""

import os
# import uuid
import logging
import time
import sys

# import google.auth
# import google.generativeai as genai
from google.adk import Agent
from google.adk.sessions import InMemorySessionService, DatabaseSessionService
from google.adk.artifacts import InMemoryArtifactService
from google.adk import Runner
from google.genai import types
from google.adk.events import Event, EventActions

from opik.integrations.adk import OpikTracer
import opik

from dotenv import load_dotenv

from fronend.streamlit_chat import cookie
# from .libs.storage import GCPStorage
# from .libs.bhashini import (DhruvaSpeechProcessor,
#                             DhruvaTranslator,
#                             LanguageCodes,
#                             convert_to_wav_with_ffmpeg)

from .models.chat import Request
# from .models.callbacks import before_tool

# from .config.config import KB_BASE_URL, LLM_CONFIG, GOOGLE_AGENT
from .config.config import LLM_CONFIG, GOOGLE_AGENT
from .prompt import INSTRUCTION, GLOBAL_INSTRUCTION
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

from .tools.userinfo_tools import validate_user, load_details_for_registered_users, update_name
from .tools.cert_tools import (
        handle_issued_certificate_issues,
        list_pending_contents,
        handle_certificate_qr_issues,
        handle_certificate_name_issues,
        )
from .tools.otp_auth_tools import send_otp, verify_otp, check_channel
from .tools.zoho_ticket_tools import create_support_ticket_tool
# from .tools.faq_tools import answer_general_questions
from .tools.faq_tools import (
    answer_general_questions,
    initialize_environment,
    initialize_knowledge_base
)

from .tools.tools import (
    # answer_general_questions,
    update_phone_number_tool,
)

logger = logging.getLogger(__name__)

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
        print(response)
        logging.info("Knowledge base initialized successfully.")
        # return queryengine
    except (ValueError, FileNotFoundError, ImportError, RuntimeError) as e:
        logging.info("Error initializing knowledge base: %s", e)
        sys.exit(1)

    logging.info("✅ Successfully initialized tools and knowledge base")

initialize_env()


class ChatAgent:
    """
    ChatAgent class to manage chat sessions and interactions with the Gemini model.
    """
    app_name = "iGotAssitant"
    llm = None
    user_id = None
    # session_service = InMemorySessionService()
    session_service = DatabaseSessionService(db_url=os.getenv("POSTGRES_URL"))
    artifact_service = InMemoryArtifactService()
    runner = None # Runner(app_name=app_name, agent=llm, session_service=session_service)
    session = None

    def __init__(self):
        load_dotenv()
        self.chat_sessions = {}

        # credentials, _ = google.auth.load_credentials_from_file(
        # os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))
        # genai.configure(credentials=credentials)

        if not GOOGLE_AGENT:
            print("Initializing the Generative AI model.")
            # self.llm = genai.GenerativeModel(
            #     model_name=os.getenv("GEMINI_MODEL"),
            #     generation_config=LLM_CONFIG,
            #     tools=[
            #         validate_user,
            #         load_details_for_registered_users,
            #         answer_general_questions,
            #         create_support_ticket_tool,
            #         handle_certificate_issues,
            #         send_otp,
            #         verify_otp,
            #         update_phone_number_tool,
            #         list_pending_contents,
            #     ]
            # )
        else:
            # print("Initializing Google ADK agent")
            self.llm = Agent(
                model=os.getenv("GEMINI_MODEL"),
                name="iGotAssistant",
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
                # before_tool_callback=before_tool,
            )

            self.runner = Runner(app_name=self.app_name,
                                 agent=self.llm, session_service=self.session_service,
                                 artifact_service=self.artifact_service)
            # print(self.runner)
            # print(self.session)
        logger.info("ChatAgent initialized")

    async def start_new_session(self, user_id, request: Request) -> dict:
        """Start a new chat session with initial instructions."""
        print(f'{user_id} :: Trying to start new session {request.session_id}')
        if not GOOGLE_AGENT:
            chat = self.llm.start_chat(
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
            logger.info(f"{user_id} :: New session started : %s", session_id)
        else:
            print(f'{user_id} :: Session id', request.session_id)
            # self.user_id = request.channel_id+request.session_id
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
        if GOOGLE_AGENT:
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
                    print(f"{user_id} :: Setting the WEB ......")
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
                        author="system", # Or 'agent', 'tool' etc.
                        actions=action_with_update,
                        timestamp=time_now,
                        # content might be None or represent the action taken
                    )

                    await self.runner.session_service.append_event(session, system_event)

                    # session.state["is_authenticated"] = True
                    # session.
                    # Set a flag in the session state to indicate authentication
                    # session.state["web"] = True
                    # session.state["user_id"] = user_id

                    # No need to call update_session for InMemorySessionService
                print(f'{user_id} :: Setting state', session.state.get("web"))
                print(f'{user_id} :: Setting user_id', session.state.get("user_id"))

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
                        print(f"{user_id} :: {event.author} : {event.content.parts[0].text}")
                        response = event.content.parts[0].text
            except Exception as e:
                print(str(e))

            return {"text": response, "audio": audio_url}

        else:
            # session_id = request.channel_id + "_" + request.session_id
            session_id = request.session_id
            if session_id not in self.chat_sessions:
                self.start_new_session(user_id, request)

            # language = LanguageCodes.__members__.get(request.language.upper())
            # logger.info('Language update %s for session %s', language, session_id)

            # if request.audio:
            #     wav_data = await convert_to_wav_with_ffmpeg(request.audio)
            #     request.text = await speech_processor.speech_to_text(wav_data, language)

            # if request.language != "en":
            #     request.text = await translator.translate_text(request.text, language, LanguageCodes.EN)

            logger.info('Request : %s', request.model_dump())
            session_data = self.chat_sessions[session_id]
            chat = session_data["chat"]
            history = session_data["history"]

            response = chat.send_message(request.text)
            print(response)
            content = response.text

            # translated_text = await translator.translate_text(content, LanguageCodes.EN, language) \
            #     if request.language != "en" else content

            # audio_id = uuid.uuid4()
            # if request.audio:
            #     audio_content = await speech_processor.text_to_speech(translated_text, language)
            #     storage.write_file(
            #         f"content/support_files/{str(audio_id)}.mp3",
            #         audio_content,
            #         mime_type="audio/mpeg"
            #     )

            # audio_url = KB_BASE_URL + f"/content-store/content/support_files/{str(audio_id)}.mp3" \
            #     if request.audio else None

            logger.info("Audio URL : %s", audio_url)
            # Update chat history
            history.append({"role": "user", "parts": [request.text]})
            history.append({"role": "model", "parts": [content]})


            logger.info('Response : %s', response)
            # return {"text": translated_text, "audio": audio_url}
            return {"text": response.text, "audio": audio_url}
