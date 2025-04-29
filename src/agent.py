"""
Agent service implementation for the Karmayogi Bharat chatbot.
"""

import os
import uuid

import google.auth
import google.generativeai as genai

from dotenv import load_dotenv
from .libs.storage import GCPStorage
from .libs.bhashini import (DhruvaSpeechProcessor,
                            DhruvaTranslator,
                            LanguageCodes,
                            convert_to_wav_with_ffmpeg)

from .models.chat import StartChat
from .config.config import KB_BASE_URL, LLM_CONFIG
from .prompt import INSTRUCTION, GLOBAL_INSTRUCTION
from .tools.tools import (
    validate_user,
    load_details_for_registered_users,
    answer_general_questions,
    create_support_ticket_tool,
    handle_certificate_issues,
    verify_otp,
    send_otp,
    update_phone_number_tool,
    list_pending_contents
)

speech_processor = DhruvaSpeechProcessor()
translator = DhruvaTranslator()
storage = GCPStorage()

class ChatAgent:
    """
    ChatAgent class to manage chat sessions and interactions with the Gemini model.
    """
    def __init__(self):
        load_dotenv()
        self.chat_sessions = {}

        credentials, _ = google.auth.load_credentials_from_file(
        os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))
        genai.configure(credentials=credentials)

        self.llm_model = genai.GenerativeModel(
            model_name=os.getenv("GEMINI_MODEL"),
            generation_config=LLM_CONFIG,
            tools=[
                validate_user,
                load_details_for_registered_users,
                answer_general_questions,
                create_support_ticket_tool,
                handle_certificate_issues,
                send_otp,
                verify_otp,
                update_phone_number_tool,
                list_pending_contents,
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

    async def send_message(self, request: StartChat) -> dict:
        """Send a message in an existing chat session."""
        session_id = request.channel_id + "_" + request.session_id
        if session_id not in self.chat_sessions:
            self.start_new_session(request)

        language = LanguageCodes.__members__.get(request.language.upper())

        if request.audio:
            print("Audio received")
            wav_data = await convert_to_wav_with_ffmpeg(request.audio)
            request.text = await speech_processor.speech_to_text(wav_data, language)

        if request.language != "en":
            request.text = await translator.translate_text(request.text, language, LanguageCodes.EN)

        print(f"Received message: {request.text}")
        session_data = self.chat_sessions[session_id]
        chat = session_data["chat"]
        history = session_data["history"]

        response = chat.send_message(request.text)
        content = response.text

        translated_text = await translator.translate_text(content, LanguageCodes.EN, language) \
            if request.language != "en" else content

        audio_id = uuid.uuid4()
        if request.audio:
            audio_content = await speech_processor.text_to_speech(translated_text, language)
            storage.write_file(
                f"content/support_files/{str(audio_id)}.mp3",
                audio_content,
                mime_type="audio/mpeg"
            )

        audio_url = KB_BASE_URL + f"/content-store/content/support_files/{str(audio_id)}.mp3" \
            if request.audio else None

        print(f'Audio URL: {audio_url}')
        # Update chat history
        history.append({"role": "user", "parts": [request.text]})
        history.append({"role": "model", "parts": [content]})


        return {"text": translated_text, "audio": audio_url}
