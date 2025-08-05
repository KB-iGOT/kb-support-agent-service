# utils/request_context.py
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from utils.redis_session_service import ChatMessage

logger = logging.getLogger(__name__)


@dataclass
class RequestContext:
    """Request-scoped context to avoid global state issues"""
    user_id: str
    session_id: str
    cookie: str
    cookie_hash: str
    user_context: Optional[Dict[str, Any]] = None
    chat_history: Optional[List[ChatMessage]] = None
    is_anonymous: bool = False
    session_info: Optional[Dict[str, Any]] = None

    # NEW: Language and translation context
    detected_language: str = 'en'
    language_name: str = 'English'
    original_message: str = ''
    english_message: str = ''
    needs_translation: bool = False
    translation_context: Optional[Dict[str, Any]] = None

    def set_translation_context(self, translation_context: Dict[str, Any]):
        """Set translation context from translation service"""
        self.detected_language = translation_context.get('detected_language', 'en')
        self.language_name = translation_context.get('language_name', 'English')
        self.original_message = translation_context.get('original_message', '')
        self.english_message = translation_context.get('english_message', '')
        self.needs_translation = translation_context.get('needs_translation', False)
        self.translation_context = translation_context

        logger.info(f"Set translation context - Language: {self.language_name}, Needs translation: {self.needs_translation}")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for passing to tools"""
        return {
            'user_id': self.user_id,
            'session_id': self.session_id,
            'cookie': self.cookie,
            'cookie_hash': self.cookie_hash,
            'user_context': self.user_context,
            'chat_history': [msg.to_dict() if hasattr(msg, 'to_dict') else msg for msg in (self.chat_history or [])],
            'is_anonymous': self.is_anonymous,
            'session_info': self.session_info,
            'detected_language': self.detected_language,
            'language_name': self.language_name,
            'original_message': self.original_message,
            'english_message': self.english_message,
            'needs_translation': self.needs_translation,
            'translation_context': self.translation_context
        }

    def get_processing_message(self) -> str:
        """Get the message that should be used for processing (English)"""
        return self.english_message if self.english_message else self.original_message

    def get_user_name(self) -> str:
        """Get user's name safely"""
        if self.user_context and 'profile' in self.user_context:
            return self.user_context['profile'].get('firstName', 'User')
        return 'User'

    def get_enrollment_summary(self) -> Dict[str, Any]:
        """Get enrollment summary safely"""
        if self.user_context:
            return self.user_context.get('enrollment_summary', {})
        return {}

    def get_course_enrollments(self) -> List[Dict[str, Any]]:
        """Get course enrollments safely"""
        if self.user_context:
            return self.user_context.get('course_enrollments', [])
        return []

    def get_event_enrollments(self) -> List[Dict[str, Any]]:
        """Get event enrollments safely"""
        if self.user_context:
            return self.user_context.get('event_enrollments', [])
        return []