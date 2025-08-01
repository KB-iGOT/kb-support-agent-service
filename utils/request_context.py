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
            'session_info': self.session_info
        }

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