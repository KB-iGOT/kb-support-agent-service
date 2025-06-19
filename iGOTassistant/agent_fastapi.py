
"""
Agent service implementation for the Karmayogi Bharat chatbot.
"""

import os
# import uuid
import logging

# import google.auth
# import google.generativeai as genai
from google.adk import Agent
from google.adk.sessions import InMemorySessionService
from google.adk.artifacts import InMemoryArtifactService
from google.adk import Runner
from google.genai import types

from dotenv import load_dotenv
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
from .tools.otp_auth_tools import send_otp, verify_otp
from .tools.zoho_ticket_tools import create_support_ticket_tool
from .tools.faq_tools import answer_general_questions
from .tools.tools import (
    # answer_general_questions,
    update_phone_number_tool,
)

logger = logging.getLogger(__name__)

# speech_processor = DhruvaSpeechProcessor()
# translator = DhruvaTranslator()
# storage = GCPStorage()

class ChatAgent:
    """
    ChatAgent class to manage chat sessions and interactions with the Gemini model.
    """
    app_name = "iGotAssitant"
    llm = None
    user_id = None
    session_service = InMemorySessionService()
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
            print("Initializing Google ADK agent")
            self.llm = Agent(
                model=os.getenv("GEMINI_MODEL"),
                name="iGotAssistant",
                generate_content_config=LLM_CONFIG,
                instruction=INSTRUCTION,
                global_instruction=GLOBAL_INSTRUCTION,
                tools=[
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
                # before_tool_callback=before_tool,
            )

            self.runner = Runner(app_name=self.app_name,
                                 agent=self.llm, session_service=self.session_service,
                                 artifact_service=self.artifact_service)
            print(self.runner)
            print(self.session)
        logger.info("ChatAgent initialized")

    async def start_new_session(self, user_id, request: Request) -> dict:
        """Start a new chat session with initial instructions."""
        print(f'Trying to start new session {request.session_id}')
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
            logger.info("New session started : %s", session_id)
        else:
            print('Session id', request.session_id)
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
        if GOOGLE_AGENT:
            response = ""
            audio_url = None
            content = types.Content(
                role='user',
                parts=[types.Part.from_text(text=request.text)]
            )

            print('* user : ', content.model_dump(exclude_none=True))
            print('-'*40)
            print(request, self.session, self.user_id)
            session_id = request.channel_id + "_" + request.session_id
            # print(self.session.id, self.session.user_id)
            try:
                async for event in self.runner.run_async(
                        # user_id=self.user_id,
                        user_id=user_id,
                        # user_id=request.user_id,
                        # session_id=request.session_id,
                        session_id=request.session_id,
                        new_message=content):
                    print(event)
                    if event.content.parts and event.content.parts[0].text:
                        print(f"{event.author} : {event.content.parts[0].text}")
                        response = event.content.parts[0].text
            except Exception as e:
                print(str(e))

            return {"text": response, "audio": audio_url}




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
