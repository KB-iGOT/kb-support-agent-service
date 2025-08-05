# utils/translation_service.py - Fixed async/threading issues

import asyncio
import logging
import os
from functools import lru_cache
from typing import Dict, Any
import threading

logger = logging.getLogger(__name__)


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
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")

    @lru_cache(maxsize=1000)
    def _detect_language_cached(self, text_hash: str, text: str) -> str:
        """Cached language detection to avoid repeated API calls"""
        from langdetect import detect, LangDetectException
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
            import traceback
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


async def translate_to_english(text: str, source_lang: str) -> str:
    """Translate text to English for processing"""
    return await translation_service.translate_to_english(text, source_lang)


async def translate_response_to_user_language(text: str, target_lang: str) -> str:
    """Translate response back to user's language"""
    return await translation_service.translate_from_english(text, target_lang)


async def get_translation_context(user_message: str) -> Dict[str, Any]:
    """Get complete translation context for a message"""
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