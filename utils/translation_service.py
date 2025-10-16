import httpx
import os
import asyncio
import logging
import json
import base64
import threading
import traceback
import time
from functools import lru_cache
from typing import Dict, Any
from langdetect import detect, LangDetectException

# --- CONFIG LOADER ---
def load_bhashini_config(config_type: str):
    """
    Load Bhashini pipeline config for 'asr', 'tts', or 'nmt'.
    Returns the parsed JSON dict, but strips any API key values for safety.
    """
    config_path = os.path.join(os.path.dirname(__file__), f"../bhashini_configs/{config_type}_pipeline.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    # Remove/ignore any API key value in the config for safety
    for k in ["pipelineInferenceAPIEndPoint", "pipelineInferenceSocketEndPoint"]:
        if k in config and "inferenceApiKey" in config[k]:
            if "value" in config[k]["inferenceApiKey"]:
                # Optionally log a warning if the config contains a value
                logger.warning(f"[SECURITY] API key found in {config_type}_pipeline.json. This value will NOT be used. Please remove it from the file.")
                config[k]["inferenceApiKey"]["value"] = "<from_env>"
    return config

# --- MODEL SELECTOR ---
def get_service_config(config_type: str, lang: str):
    """
    Given config_type ('asr', 'tts', 'nmt') and language code, return the config dict for that language.
    """
    config = load_bhashini_config(config_type)
    task_type = config_type if config_type != 'nmt' else 'translation'
    for task in config.get("pipelineResponseConfig", []):
        if task.get("taskType") == task_type:
            for entry in task.get("config", []):
                lang_info = entry.get("language", {})
                if lang_info.get("sourceLanguage") == lang:
                    return entry
    return None

logger = logging.getLogger(__name__)
# --- BHASHINI TRANSLATOR ---

class BhashiniTranslator:
    def __init__(self, api_url: str = None, api_key: str = None):
        self.api_url = api_url or os.getenv("BHASHINI_API_URL", "https://dhruva-api.bhashini.gov.in/services/inference/pipeline")
        # Always read API key from environment or .env, never from config JSON
        self.api_key = api_key or os.getenv("BHASHINI_API_KEY", "")
        # Async HTTP client with connection pooling for high concurrency
        # Limits: 100 connections per host, 200 total, 60s keepalive
        self._client = httpx.AsyncClient(
            timeout=30.0,
            limits=httpx.Limits(max_keepalive_connections=100, max_connections=200, keepalive_expiry=60)
        )

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        # Use config for serviceId selection
        service_entry = get_service_config('nmt', source_lang)
        service_id = service_entry["serviceId"] if service_entry else os.getenv("BHASHINI_SERVICE_ID", "ai4bharat/indictrans-v2-all-gpu--t4")
        headers = {
            'Accept': '*/*',
            'User-Agent': 'Thunder Client (https://www.thunderclient.com)',
            'Authorization': self.api_key,  # No Bearer for translation
            'Content-Type': 'application/json',
        }
        payload = {
            "pipelineTasks": [
                {
                    "taskType": "translation",
                    "config": {
                        "language": {
                            "sourceLanguage": source_lang,
                            "targetLanguage": target_lang
                        },
                        "serviceId": service_id
                    }
                }
            ],
            "inputData": {
                "input": [
                    {"source": text}
                ]
            }
        }
        
        start_time = time.perf_counter()
        try:
            response = await self._client.post(self.api_url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            translated = data["pipelineResponse"][0]["output"][0]["target"]
            duration = (time.perf_counter() - start_time) * 1000
            logger.info(f"[TRANSLATE] Completed: Response Translation | Duration: {duration:.2f}ms | {source_lang}→{target_lang}: '{text[:30]}...' → '{translated[:30]}...'")
            return translated
        except Exception as e:
            duration = (time.perf_counter() - start_time) * 1000
            logger.warning(f"[TRANSLATE] Bhashini failed ({source_lang}→{target_lang}): {e}. Duration: {duration:.2f}ms. Falling back to Google.")
            # Debug details - uncomment if needed for troubleshooting
            # logger.error(f"URL: {self.api_url}, Service ID: {service_id}")
            # logger.error(f"Payload: {str(payload)[:500]}...")
            # Fallback to Google Translate async method
            try:
                from utils.translation_service import translation_service
                translated = await translation_service._translate_text(text, source_lang, target_lang)
                logger.info(f"[TRANSLATE] Google Translate fallback {source_lang}→{target_lang}: '{text[:30]}...' → '{translated[:30]}...'")
                return translated
            except Exception as fallback_e:
                logger.error(f"[TRANSLATE] Google Translate fallback also failed: {fallback_e}")
                return text

    async def asr(self, audio_bytes: bytes, source_lang: str, service_id: str = None, audio_format: str = "flac", sampling_rate: int = 16000) -> str:
        """
        Transcribe audio using Bhashini ASR API (audio as base64 in JSON).
        Returns the transcribed text or raises Exception on failure.
        """
        url = os.getenv("BHASHINI_ASR_URL", "https://dhruva-api.bhashini.gov.in/services/inference/pipeline")
        api_key = self.api_key
        # Use config for service_id
        if not service_id:
            service_entry = get_service_config('asr', source_lang)
            service_id = service_entry["serviceId"] if service_entry else os.getenv("BHASHINI_ASR_SERVICE_ID", "ai4bharat/conformer-multilingual-dravidian-gpu--t4")
        headers = {
            'Accept': '*/*',
            'User-Agent': 'Thunder Client (https://www.thunderclient.com)',
            'Authorization': api_key,  # No Bearer for ASR
            'Content-Type': 'application/json',
        }
        # Ensure audio_bytes is bytes and convert to base64 string
        if not isinstance(audio_bytes, bytes):
            raise ValueError("audio_bytes must be of type bytes")
        audio_b64 = base64.b64encode(audio_bytes).decode('ascii')
        payload = {
            "pipelineTasks": [
                {
                    "taskType": "asr",
                    "config": {
                        "language": {"sourceLanguage": source_lang},
                        "serviceId": service_id,
                        "audioFormat": audio_format,
                        "samplingRate": sampling_rate
                    }
                }
            ],
            "inputData": {"audio": [{"audioContent": audio_b64}]}
        }
        
        start_time = time.perf_counter()
        try:
            # Debug logging - comment out in production
            # logger.debug(f"[ASR] Requesting Bhashini ASR: url={url}, api_key={api_key[:6]}***, service_id={service_id}, lang={source_lang}")
            response = await self._client.post(url, headers=headers, json=payload)
            # logger.debug(f"[ASR] Response status: {response.status_code}")
            response.raise_for_status()
            data = response.json()
            transcript = data["pipelineResponse"][0]["output"][0]["source"]
            duration = (time.perf_counter() - start_time) * 1000
            logger.info(f"[ASR] Completed: Audio Transcription | Duration: {duration:.2f}ms | {source_lang}: {transcript[:50]}...")
            return transcript
        except Exception as e:
            duration = (time.perf_counter() - start_time) * 1000
            logger.error(f"[ASR] Bhashini ASR failed for {source_lang}: {e} | Duration: {duration:.2f}ms")
            # Debug details - uncomment if needed for troubleshooting
            # logger.error(f"URL: {url}, Service ID: {service_id}")
            # logger.error(f"Payload structure: {str(payload_log)[:200]}...")
            raise

    async def tts(self, text: str, target_lang: str) -> bytes:
        """
        Synthesize speech using Bhashini TTS API.
        Returns audio bytes or raises Exception on failure.
        """
        url = os.getenv("BHASHINI_TTS_URL", "https://dhruva-api.bhashini.gov.in/services/inference/pipeline")
        api_key = self.api_key
        # Use config for service_id
        service_entry = get_service_config('tts', target_lang)
        service_id = service_entry["serviceId"] if service_entry else os.getenv("BHASHINI_TTS_SERVICE_ID", "ai4bharat/indic-tts-coqui-misc-gpu--t4")
        headers = {
            'Accept': '*/*',
            'User-Agent': 'Thunder Client (https://www.thunderclient.com)',
            'Authorization': api_key,  # No Bearer for TTS
            'Content-Type': 'application/json',
        }
        payload = {
            "pipelineTasks": [
                {
                    "taskType": "tts",
                    "config": {
                        "language": {"sourceLanguage": target_lang},
                        "serviceId": service_id,
                        "gender": "female",
                        "samplingRate": 8000
                    }
                }
            ],
            "inputData": {"input": [{"source": text}]}
        }
        
        start_time = time.perf_counter()
        try:
            # Debug logging - comment out in production
            # logger.debug(f"[TTS] Requesting Bhashini TTS: url={url}, api_key={api_key[:6]}***, service_id={service_id}, lang={target_lang}")
            response = await self._client.post(url, headers=headers, json=payload)
            # logger.debug(f"[TTS] Response status: {response.status_code}")
            response.raise_for_status()
            data = response.json()
            # Robustly handle Bhashini TTS response format
            pipeline_response = data.get("pipelineResponse")
            if not pipeline_response or not isinstance(pipeline_response, list) or len(pipeline_response) == 0:
                logger.error(f"[TTS] Unexpected response: {data}")
                raise Exception("No pipelineResponse found in TTS response")
            pipeline_resp = pipeline_response[0]
            audio_b64 = None
            # Try old format first
            if pipeline_resp.get("output") and pipeline_resp["output"] and pipeline_resp["output"][0].get("audio"):
                audio_b64 = pipeline_resp["output"][0]["audio"]
            # Try new format: 'audio' array with 'audioContent'
            elif pipeline_resp.get("audio") and pipeline_resp["audio"] and pipeline_resp["audio"][0].get("audioContent"):
                audio_b64 = pipeline_resp["audio"][0]["audioContent"]
            if not audio_b64:
                logger.error(f"[TTS] No audio found in pipelineResponse: {pipeline_resp}")
                raise Exception("No audio found in TTS response")
            audio_bytes = base64.b64decode(audio_b64)
            duration = (time.perf_counter() - start_time) * 1000
            logger.info(f"[TTS] Completed: Speech Synthesis | Duration: {duration:.2f}ms | {target_lang}: {len(audio_bytes)} bytes")
            return audio_bytes
        except Exception as e:
            duration = (time.perf_counter() - start_time) * 1000
            logger.error(f"[TTS] Bhashini TTS failed for {target_lang}: {e} | Duration: {duration:.2f}ms")
            # Debug details - uncomment if needed for troubleshooting
            # logger.error(f"URL: {url}, Service ID: {service_id}")
            # logger.error(f"Text length: {len(text)} chars")
            raise

    async def close(self):
        """Close the HTTP client and cleanup resources"""
        await self._client.aclose()
        logger.info("[BhashiniTranslator] HTTP client closed")

# --- AUDIO PIPELINE LOGIC ---
async def process_audio_pipeline(input_data: Dict[str, Any], llm_func) -> Dict[str, Any]:
    """
    If 'audio' is present in input_data, use Bhashini ASR to transcribe, translate to English, send to LLM,
    translate back, and use TTS for audio output. Returns dict with 'text', 'audio', and 'lang'.
    llm_func: async function that takes English text and returns English response.
    """
    if "audio" not in input_data:
        return {"error": "No audio provided"}

    audio_bytes = input_data["audio"]  # Should be bytes
    source_lang = input_data.get("input_language", "hi")
    target_lang = source_lang

    # 1. ASR: Speech to text
    try:
        transcript = await bhashini_translator.asr(audio_bytes, source_lang)
    except Exception as e:
        return {"error": f"ASR failed: {e}"}

    # 2. Translate to English (if needed)
    english_text = await translate_to_english(transcript, source_lang)

    # 3. LLM: Get response in English
    try:
        llm_response_en = await llm_func(english_text)
    except Exception as e:
        return {"error": f"LLM failed: {e}"}

    # 4. Translate back to user language
    response_user_lang = await translate_response_to_user_language(llm_response_en, target_lang)

    # 5. TTS: Text to speech
    try:
        audio_response = await bhashini_translator.tts(response_user_lang, target_lang)
    except Exception as e:
        return {"error": f"TTS failed: {e}", "text": response_user_lang}

    return {
        "text": response_user_lang,
        "audio": audio_response,
        "lang": target_lang,
        "transcript": transcript,
        "llm_response_en": llm_response_en
    }

# --- PIPELINE PLACEHOLDER ---
def bhashini_pipeline_placeholder(*args, **kwargs):
    """
    Placeholder for future Bhashini pipeline optimization (single API call for ASR+NMT+TTS).
    """
    logger.info("[PIPELINE] Bhashini pipeline placeholder called. Not implemented.")
    return {"error": "Pipeline optimization not implemented yet."}

# Global Bhashini translator instance
bhashini_translator = BhashiniTranslator()
# utils/translation_service.py - Fixed async/threading issues




class TranslationService:
    """Standalone translation service utility with proper async handling"""

    def __init__(self):
        self.supported_languages = {
            'hi': 'Hindi',
            'en': 'English'
        }

        self.google_translate_client = None
        self.google_api_key = None
        self._translation_cache = {}  # Simple in-memory cache
        self._cache_lock = threading.Lock()
        self._initialize_translation_client()

    def _initialize_translation_client(self):
        """Initialize Google Translate client if credentials available"""
        try:
            # Debug: Check environment variables
            google_creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            google_api_key = os.getenv("GOOGLE_API_KEY")

            logger.info(f"GOOGLE_APPLICATION_CREDENTIALS: {'Set' if google_creds else 'Not set'}")
            logger.info(f"GOOGLE_API_KEY: {'Set' if google_api_key else 'Not set'}")

            if google_api_key:
                logger.info(f"API Key preview: {google_api_key[:10]}...")

            # Try different ways to initialize Google Translate
            if google_creds:
                logger.info("Attempting to initialize with service account credentials...")
                from google.cloud import translate_v2 as translate
                self.google_translate_client = translate.Client()
                logger.info("✅ Google Cloud Translate client initialized with service account")

            elif google_api_key:
                logger.info("Attempting to initialize with API key using REST API...")
                self.google_api_key = google_api_key
                self.google_translate_client = "api_key_mode"
                logger.info("✅ Google Translate configured for API key mode")

                # Test the API key with a synchronous test
                try:
                    import httpx

                    url = "https://translation.googleapis.com/language/translate/v2"
                    params = {
                        'key': google_api_key,
                        'q': 'hello',
                        'target': 'hi',
                        'format': 'text'
                    }

                    with httpx.Client() as client:
                        response = client.post(url, params=params)

                        if response.status_code == 200:
                            result = response.json()
                            translated_text = result['data']['translations'][0]['translatedText']
                            logger.info(f"✅ API key test successful: hello -> {translated_text}")
                        else:
                            logger.error(f"❌ API key test failed: {response.status_code} - {response.text}")
                            self.google_translate_client = None
                            self.google_api_key = None

                except Exception as test_error:
                    logger.error(f"❌ API key translation test failed: {test_error}")
                    self.google_translate_client = None
                    self.google_api_key = None

            else:
                logger.warning("❌ No Google Translate credentials found. Translation will be limited.")

        except ImportError as import_error:
            logger.error(f"❌ Failed to import Google Cloud Translate library: {import_error}")
            logger.error("Install with: pip install google-cloud-translate")

        except Exception as e:
            logger.error(f"❌ Could not initialize Google Translate: {e}")
            logger.error(f"Exception type: {type(e)}")
            logger.error(f"Full traceback: {traceback.format_exc()}")

    @lru_cache(maxsize=1000)
    def _detect_language_cached(self, text_hash: str, text: str) -> str:
        """Cached language detection to avoid repeated API calls"""
        try:
            detected_lang = detect(text)

            if detected_lang in self.supported_languages:
                logger.debug(f"Detected language: {detected_lang} ({self.supported_languages[detected_lang]})")
                return detected_lang
            else:
                logger.debug(f"Detected unsupported language: {detected_lang}, defaulting to English")
                return 'en'

        except (LangDetectException, Exception) as e:
            logger.debug(f"Language detection failed for text: {e}")
            return 'en'  # Default to English

    async def detect_language(self, text: str) -> str:
        """Detect the language of input text with caching"""
        if not text or len(text.strip()) < 3:
            return 'en'

        # Create a simple hash for caching (first 100 chars)
        text_hash = str(hash(text[:100]))
        return self._detect_language_cached(text_hash, text)

    def _get_cache_key(self, text: str, source_lang: str, target_lang: str) -> str:
        """Generate cache key for translation"""
        return f"{source_lang}:{target_lang}:{hash(text)}"

    def _get_cached_translation(self, cache_key: str) -> str:
        """Get translation from cache thread-safely"""
        with self._cache_lock:
            return self._translation_cache.get(cache_key)

    def _set_cached_translation(self, cache_key: str, translation: str):
        """Set translation in cache thread-safely"""
        with self._cache_lock:
            # Keep cache size reasonable
            if len(self._translation_cache) > 1000:
                # Remove oldest half of cache
                keys_to_remove = list(self._translation_cache.keys())[:500]
                for key in keys_to_remove:
                    del self._translation_cache[key]

            self._translation_cache[cache_key] = translation

    async def _translate_with_rest_api(self, text: str, source_lang: str, target_lang: str) -> str:
        """Translate using Google Translate REST API with API key"""
        try:
            import httpx

            url = "https://translation.googleapis.com/language/translate/v2"
            params = {
                'key': self.google_api_key,
                'q': text,
                'source': source_lang,
                'target': target_lang,
                'format': 'text'
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(url, params=params)

                if response.status_code == 200:
                    result = response.json()
                    translated_text = result['data']['translations'][0]['translatedText']
                    logger.debug(f"REST API translation successful: {text[:30]}... -> {translated_text[:30]}...")
                    return translated_text
                else:
                    logger.error(f"REST API translation failed: {response.status_code} - {response.text}")
                    return text

        except Exception as e:
            logger.error(f"REST API translation error: {e}")
            return text

    async def _translate_with_client_library(self, text: str, source_lang: str, target_lang: str) -> str:
        """Translate using Google Cloud client library (synchronous in executor)"""
        try:
            def _sync_translate():
                result = self.google_translate_client.translate(
                    text,
                    source_language=source_lang,
                    target_language=target_lang
                )
                return result['translatedText']

            # Run synchronous client library call in executor
            loop = asyncio.get_event_loop()
            translated_text = await loop.run_in_executor(None, _sync_translate)

            logger.debug(f"Client library translation result: {translated_text[:50]}...")
            return translated_text

        except Exception as e:
            logger.error(f"Client library translation error: {e}")
            return text

    async def _translate_text(self, text: str, source_lang: str, target_lang: str) -> str:
        """Core translation method with proper async handling"""
        try:
            # Check cache first
            cache_key = self._get_cache_key(text, source_lang, target_lang)
            cached_result = self._get_cached_translation(cache_key)
            if cached_result:
                logger.debug(f"Using cached translation for: {text[:30]}...")
                return cached_result

            # Debug: Check if client is available
            logger.debug(f"Translation attempt: {source_lang} -> {target_lang}")
            logger.debug(f"Google client mode: {self.google_translate_client}")

            translated_text = text  # Default fallback

            if self.google_translate_client == "api_key_mode":
                # Use REST API for API key authentication
                logger.debug(f"Using REST API for translation: {text[:50]}...")
                translated_text = await self._translate_with_rest_api(text, source_lang, target_lang)

            elif self.google_translate_client:
                # Use client library for service account authentication
                logger.debug(f"Using client library for translation: {text[:50]}...")
                translated_text = await self._translate_with_client_library(text, source_lang, target_lang)

            else:
                # Fallback: return original text if no translation service
                logger.warning(f"❌ No translation service available for {source_lang} -> {target_lang}")
                logger.warning("Returning original text unchanged")
                translated_text = text

            # Cache the result
            self._set_cached_translation(cache_key, translated_text)
            return translated_text

        except Exception as e:
            logger.error(f"❌ Translation failed ({source_lang} -> {target_lang}): {e}")
            logger.error(f"Exception type: {type(e)}")
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return text

    async def translate_to_english(self, text: str, source_lang: str) -> str:
        """Translate text from source language to English"""
        if source_lang == 'en' or not text:
            return text

        try:
            translated_text = await self._translate_text(text, source_lang, 'en')

            if translated_text != text:
                logger.info(
                    f"✅ Translated from {source_lang} to English: '{text[:30]}...' -> '{translated_text[:30]}...'")
            else:
                logger.warning(f"⚠️  Translation unchanged from {source_lang} to English")

            return translated_text

        except Exception as e:
            logger.error(f"❌ Translation to English failed: {e}")
            return text

    async def translate_from_english(self, text: str, target_lang: str) -> str:
        """Translate text from English to target language"""
        if target_lang == 'en' or not text:
            return text

        try:
            translated_text = await self._translate_text(text, 'en', target_lang)

            if translated_text != text:
                logger.info(
                    f"✅ Translated from English to {target_lang}: '{text[:30]}...' -> '{translated_text[:30]}...'")
            else:
                logger.warning(f"⚠️  Translation unchanged from English to {target_lang}")

            return translated_text

        except Exception as e:
            logger.error(f"❌ Translation from English failed: {e}")
            return text

    def get_language_name(self, lang_code: str) -> str:
        """Get human-readable language name"""
        return self.supported_languages.get(lang_code, f"Unknown ({lang_code})")

    async def translate_error_message(self, error_message: str, target_lang: str) -> str:
        """Translate error messages to user's language"""
        if target_lang == 'en':
            return error_message

        try:
            return await self.translate_from_english(error_message, target_lang)
        except:
            return error_message  # Fallback to English


# Global translation service instance
translation_service = TranslationService()


# Convenience functions for easy import
async def detect_user_language(text: str) -> str:
    """Detect language of user input"""
    return await translation_service.detect_language(text)



# --- Modular translation using Bhashini if language specified, else fallback ---
async def translate_to_english(text: str, source_lang: str) -> str:
    """Translate text to English for processing, using Bhashini if not English and language specified."""
    if not text or source_lang == 'en':
        return text
    # Use Bhashini for non-English
    if source_lang and source_lang != 'en':
        return await bhashini_translator.translate(text, source_lang, 'en')
    # Fallback to Google
    return await translation_service.translate_to_english(text, source_lang)

async def translate_response_to_user_language(text: str, target_lang: str) -> str:
    """Translate response back to user's language, using Bhashini if not English and language specified."""
    if not text or target_lang == 'en':
        return text
    if target_lang and target_lang != 'en':
        return await bhashini_translator.translate(text, 'en', target_lang)
    return await translation_service.translate_from_english(text, target_lang)


async def get_translation_context(user_message: str, language: str = None) -> Dict[str, Any]:
    """Get complete translation context for a message, optionally using explicit language."""
    if language and language != 'en':
        detected_lang = language
    else:
        detected_lang = await detect_user_language(user_message)

    if detected_lang != 'en':
        english_message = await translate_to_english(user_message, detected_lang)
    else:
        english_message = user_message

    return {
        'original_message': user_message,
        'detected_language': detected_lang,
        'language_name': translation_service.get_language_name(detected_lang),
        'english_message': english_message,
        'needs_translation': detected_lang != 'en'
    }