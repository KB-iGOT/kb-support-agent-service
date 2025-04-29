"""
Bhashini integration for the speech conversion and text translation.

"""
from enum import Enum
import base64
import json
import os
import tempfile
from abc import ABC, abstractmethod
from io import BytesIO
from typing import Optional
from urllib.parse import urlparse
import aiofiles
import aiofiles.os
import requests
import httpx
from dotenv import load_dotenv
from pydub import AudioSegment

load_dotenv()


class LanguageCodes(Enum):
    """ language codes for supported languages"""
    EN = "English"
    HI = "Hindi"
    BN = "Bengali"
    GU = "Gujarati"
    MR = "Marathi"
    OR = "Oriya"
    PA = "Punjabi"
    KN = "Kannada"
    ML = "Malayalam"
    TA = "Tamil"
    TE = "Telugu"
    AF = "Afrikaans"
    AR = "Arabic"
    ZH = "Chinese"
    FR = "French"
    DE = "German"
    ID = "Indonesian"
    IT = "Italian"
    JA = "Japanese"
    KO = "Korean"
    PT = "Portuguese"
    RU = "Russian"
    ES = "Spanish"
    TR = "Turkish"


class InternalServerException(Exception):
    """ Custom exceptions for internal server errors """
    def __init__(self, message):
        super().__init__(message)
        self.message = message
        self.status_code = 500

    def __str__(self):
        return self.message


def _is_url(string) -> bool:
    try:
        result = urlparse(string)
        return all([result.scheme, result.netloc])
    except ValueError:
        return False


def get_filename_from_url(url):
    """extract base filename from url"""
    # Parse the URL to get the path
    parsed_url = urlparse(url)
    path = parsed_url.path

    # Extract the filename from the path
    filename = os.path.basename(path)
    return filename


def _get_file_extension(file_name_or_url: str) -> str:
    if file_name_or_url.startswith("http://") or file_name_or_url.startswith(
        "https://"
    ):
        file_name = get_filename_from_url(file_name_or_url)
    else:
        file_name = file_name_or_url

    _, extension = os.path.splitext(file_name)
    return extension[1:]


def convert_to_wav(source_url_or_file: str, source_type: Optional[str] = None) -> bytes:
    """audio conversion with AudioSegment"""
    if not source_type:
        source_type = _get_file_extension(source_url_or_file)

    if _is_url(source_url_or_file):
        local_file = tempfile.NamedTemporaryFile(suffix=source_type)
        response = httpx.get(source_url_or_file)
        local_file.write(response.content)
        local_file.seek(0)
        local_filename = local_file.name
    else:
        local_filename = source_url_or_file

    given_audio = AudioSegment.from_file(
        local_filename, format=source_type
    )  # run ffmpeg directly using a thread pool
    given_audio = given_audio.set_frame_rate(16000)
    given_audio = given_audio.set_channels(1)

    wav_file = BytesIO()
    given_audio.export(wav_file, format="wav", codec="pcm_s16le")

    return wav_file.getvalue()


async def convert_to_wav_with_ffmpeg(
        source_url_or_file: str, source_type: Optional[str] = None) -> bytes:
    """audio conersion with ffmpeg subprocess"""
    local_file = None
    if not source_type:
        source_type = _get_file_extension(source_url_or_file)

    if _is_url(source_url_or_file):
        local_file = tempfile.NamedTemporaryFile(suffix="." + source_type, dir=os.getcwd())

        try:
            response = requests.get(source_url_or_file, stream=True, timeout=30)
            for data in response.iter_content(chunk_size=8192):
                local_file.write(data)
            local_file.seek(0)
        except requests.exceptions.RequestException as e:
            print(f"Download error: {e}")
        local_filename = local_file.name
    else:
        local_filename = source_url_or_file

    wav_filename = os.path.basename(os.path.splitext(local_filename)[0] + ".wav")
    sound = AudioSegment.from_file(local_filename)
    sound.export(wav_filename, format="wav", codec="pcm_s16le",
                 parameters=["-ac", "1", "-ar", "16000"])

    async with aiofiles.open(wav_filename, "rb") as wav_file:
        audio_data = await wav_file.read()

    await aiofiles.os.remove(wav_filename)
    if local_file:
        local_file.close()

    return audio_data

def convert_wav_bytes_to_mp3_bytes(wav_bytes: bytes) -> bytes:
    """wave to mp3 byte conversion"""
    wav_file = BytesIO(wav_bytes)
    wav_audio = AudioSegment.from_file(wav_file, format="wav")
    wav_audio = wav_audio.set_frame_rate(44100)
    mp3_file = BytesIO()
    wav_audio.export(mp3_file, format="mp3")
    return mp3_file.getvalue()

class SpeechProcessor(ABC):
    """
    Abstract class for speech processing
    """
    @abstractmethod
    async def speech_to_text( self, wav_data: bytes, input_language: LanguageCodes,) -> str:
        """
        Convert speech to text
        """
        # pass

    @abstractmethod
    async def text_to_speech( self, text: str, input_language: LanguageCodes,) -> bytes:
        """
        Convert text to speech
        """
        # pass


class DhruvaSpeechProcessor(SpeechProcessor):
    """
    Dhruva (Bhashini) speech processor
    """
    def __init__(self):
        print("bhashini_user_id ", os.getenv("BHASHINI_USER_ID"))
        self.bhashini_user_id = os.getenv("BHASHINI_USER_ID")
        self.bhashini_api_key = os.getenv("BHASHINI_API_KEY")
        self.bhashini_pipleline_id = os.getenv("BHASHINI_PIPELINE_ID")
        self.bhashini_inference_url = (
            "https://dhruva-api.bhashini.gov.in/services/inference/pipeline"
        )

    async def perform_bhashini_config_call(
        self, task: str, source_language: str, target_language: str | None = None
    ):
        """
        Perform Bhashini config call
        """
        url = "https://meity-auth.ulcacontrib.org/ulca/apis/v0/model/getModelsPipeline"
        if task in ["asr", "tts"]:
            payload = json.dumps(
                {
                    "pipelineTasks": [
                        {
                            "taskType": task,
                            "config": {"language": {"sourceLanguage": source_language}},
                        }
                    ],
                    "pipelineRequestConfig": {"pipelineId": self.bhashini_pipleline_id},
                }
            )
        else:
            payload = json.dumps(
                {
                    "pipelineTasks": [
                        {
                            "taskType": "translation",
                            "config": {
                                "language": {
                                    "sourceLanguage": source_language,
                                    "targetLanguage": target_language,
                                }
                            },
                        }
                    ],
                    "pipelineRequestConfig": {"pipelineId": self.bhashini_pipleline_id},
                }
            )
        headers = {
            "userID": self.bhashini_user_id,
            "ulcaApiKey": self.bhashini_api_key,
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, data=payload)  # type: ignore

        return response.json()

    async def speech_to_text(
        self,
        wav_data: bytes,
        input_language: LanguageCodes,
    ) -> str:
        """
        Convert speech to text
        """
        print(f"Input Language: {input_language}")
        bhashini_asr_config = await self.perform_bhashini_config_call(
            task="asr", source_language=input_language.name.lower()
        )
        print("bhashini_asr_config", bhashini_asr_config)
        encoded_string = base64.b64encode(wav_data).decode("ascii", "ignore")
        payload = json.dumps(
            {
                "pipelineTasks": [
                    {
                        "taskType": "asr",
                        "config": {
                            "language": {
                                "sourceLanguage": bhashini_asr_config["languages"][0][
                                    "sourceLanguage"
                                ],
                            },
                            "serviceId": bhashini_asr_config["pipelineResponseConfig"][
                                0
                            ]["config"][0]["serviceId"],
                            "audioFormat": "wav",
                            "samplingRate": 16000,
                        },
                    }
                ],
                "inputData": {"audio": [{"audioContent": encoded_string}]},
            }
        )
        headers = {
            "Accept": "*/*",
            "User-Agent": "Thunder Client (https://www.thunderclient.com)",
            bhashini_asr_config["pipelineInferenceAPIEndPoint"]["inferenceApiKey"][
                "name"
            ]: bhashini_asr_config["pipelineInferenceAPIEndPoint"]["inferenceApiKey"][
                "value"
            ],
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url=self.bhashini_inference_url, headers=headers, data=payload
            )  # type: ignore
        if response.status_code != 200:
            error_message = (
                f"Request failed with response.text: {response.text} and "
                f"status_code: {response.status_code}"
            )
            raise InternalServerException(error_message)

        transcribed_text = response.json()["pipelineResponse"][0]["output"][0]["source"]
        return transcribed_text

    async def text_to_speech(
        self,
        text: str,
        input_language: LanguageCodes,
        gender="female",
    ) -> bytes:
        """
        Convert text to speech
        """
        bhashini_tts_config = await self.perform_bhashini_config_call(
            task="tts", source_language=input_language.name.lower()
        )
        payload = json.dumps(
            {
                "pipelineTasks": [
                    {
                        "taskType": "tts",
                        "config": {
                            "language": {
                                "sourceLanguage": bhashini_tts_config["languages"][0][
                                    "sourceLanguage"
                                ]
                            },
                            "serviceId": bhashini_tts_config["pipelineResponseConfig"][
                                0
                            ]["config"][0]["serviceId"],
                            "gender": gender,
                            "samplingRate": 8000,
                        },
                    }
                ],
                "inputData": {"input": [{"source": text}]},
            }
        )
        headers = {
            "Accept": "*/*",
            "User-Agent": "Thunder Client (https://www.thunderclient.com)",
            # Why is it there?
            bhashini_tts_config["pipelineInferenceAPIEndPoint"]["inferenceApiKey"][
                "name"
            ]: bhashini_tts_config["pipelineInferenceAPIEndPoint"]["inferenceApiKey"][
                "value"
            ],
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url=self.bhashini_inference_url, headers=headers, data=payload
            )  # type: ignore
        if response.status_code != 200:
            error_message = (
                f"Request failed with response.text: {response.text} and "
                f"status_code: {response.status_code}"
            )
            raise InternalServerException(error_message)

        audio_content = response.json()["pipelineResponse"][0]["audio"][0][
            "audioContent"
        ]
        audio_content = base64.b64decode(audio_content)
        new_audio_content = convert_wav_bytes_to_mp3_bytes(audio_content)
        return new_audio_content


class Translator(ABC):
    """
    Abstract class for translation
    """
    @abstractmethod
    async def translate_text(
        self,
        text: str,
        source_language: LanguageCodes,
        destination_language: LanguageCodes,
    ) -> str:
        """
        Translate text
        """
        # pass

class DhruvaTranslator(Translator):
    """
    Dhruva (Bhashini) translator
    """
    def __init__(self):
        self.bhashini_user_id = os.getenv("BHASHINI_USER_ID")
        self.bhashini_api_key = os.getenv("BHASHINI_API_KEY")
        self.bhashini_pipleline_id = os.getenv("BHASHINI_PIPELINE_ID")
        self.bhashini_inference_url = (
            "https://dhruva-api.bhashini.gov.in/services/inference/pipeline"
        )

    async def perform_bhashini_config_call(
        self, task: str, source_language: str, target_language: str | None = None
    ):
        """
        Perform Bhashini config call
        """
        url = "https://meity-auth.ulcacontrib.org/ulca/apis/v0/model/getModelsPipeline"
        if task in ["asr", "tts"]:
            payload = json.dumps(
                {
                    "pipelineTasks": [
                        {
                            "taskType": task,
                            "config": {"language": {"sourceLanguage": source_language}},
                        }
                    ],
                    "pipelineRequestConfig": {"pipelineId": "64392f96daac500b55c543cd"},
                }
            )
        else:
            payload = json.dumps(
                {
                    "pipelineTasks": [
                        {
                            "taskType": "translation",
                            "config": {
                                "language": {
                                    "sourceLanguage": source_language,
                                    "targetLanguage": target_language,
                                }
                            },
                        }
                    ],
                    "pipelineRequestConfig": {"pipelineId": self.bhashini_pipleline_id},
                }
            )
        headers = {
            "userID": self.bhashini_user_id,
            "ulcaApiKey": self.bhashini_api_key,
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, data=payload)  # type: ignore

        return response.json()

    async def translate_text(
        self,
        text: str,
        source_language: LanguageCodes,
        destination_language: LanguageCodes,
    ) -> str:
        # source = source_language.name.lower()
        source = source_language.name.lower()
        # destination = destination_language.name.lower()
        destination = destination_language.name.lower()
        # logger.info("Performing translation using Dhruva (Bhashini)")
        # logger.info(f"Input Language: {source}")
        # logger.info(f"Output Language: {destination}")

        bhashini_translation_config = await self.perform_bhashini_config_call(
            task="translation", source_language=source, target_language=destination
        )

        payload = json.dumps(
            {
                "pipelineTasks": [
                    {
                        "taskType": "translation",
                        "config": {
                            "language": {
                                "sourceLanguage": bhashini_translation_config[
                                    "languages"
                                ][0]["sourceLanguage"],
                                "targetLanguage": bhashini_translation_config[
                                    "languages"
                                ][0]["targetLanguageList"][0],
                            },
                            "serviceId": bhashini_translation_config[
                                "pipelineResponseConfig"
                            ][0]["config"][0]["serviceId"],
                        },
                    }
                ],
                "inputData": {"input": [{"source": text}]},
            }
        )
        headers = {
            "Accept": "*/*",
            "User-Agent": "Thunder Client (https://www.thunderclient.com)",
            bhashini_translation_config["pipelineInferenceAPIEndPoint"][
                "inferenceApiKey"
            ]["name"]: bhashini_translation_config["pipelineInferenceAPIEndPoint"][
                "inferenceApiKey"
            ][
                "value"
            ],
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url=self.bhashini_inference_url, headers=headers, data=payload
            )  # type: ignore
        if response.status_code != 200:
            error_message = (
                f"Request failed with response.text: {response.text} and "
                f"status_code: {response.status_code}"
            )
            raise InternalServerException(error_message)

        indic_text = response.json()["pipelineResponse"][0]["output"][0]["target"]
        return indic_text
