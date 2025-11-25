from utils.request_context import RequestContext


def _make_context(**overrides):
    base = dict(
        user_id="user-123",
        session_id="session-abc",
        cookie="cookie-value",
        cookie_hash="hash-value",
    )
    base.update(overrides)
    return RequestContext(**base)


def test_set_translation_context_updates_processing_fields():
    ctx = _make_context()
    translation_context = {
        "detected_language": "hi",
        "language_name": "Hindi",
        "original_message": "नमस्ते",
        "english_message": "Hello",
        "needs_translation": True,
    }

    ctx.set_translation_context(translation_context)

    assert ctx.detected_language == "hi"
    assert ctx.language_name == "Hindi"
    assert ctx.original_message == "नमस्ते"
    assert ctx.english_message == "Hello"
    assert ctx.needs_translation is True
    assert ctx.get_processing_message() == "Hello"


class _DummyMessage:
    def __init__(self, message_id: str, role: str, content: str):
        self.message_id = message_id
        self.role = role
        self.content = content

    def to_dict(self):
        return {
            "message_id": self.message_id,
            "role": self.role,
            "content": self.content,
        }


def test_to_dict_serializes_chat_history_entries():
    chat_messages = [
        _DummyMessage(message_id="1", role="user", content="Hi"),
        _DummyMessage(message_id="2", role="assistant", content="Hello"),
    ]
    ctx = _make_context(chat_history=chat_messages)

    serialized = ctx.to_dict()

    assert serialized["user_id"] == "user-123"
    assert serialized["chat_history"][0]["message_id"] == "1"
    assert serialized["chat_history"][1]["role"] == "assistant"


def test_get_user_name_and_enrollments_are_safe():
    user_context = {
        "profile": {"firstName": "Sanya"},
        "enrollment_summary": {"karma_points": 42},
        "course_enrollments": ["course-a"],
        "event_enrollments": ["event-a"],
    }
    ctx = _make_context(user_context=user_context)

    assert ctx.get_user_name() == "Sanya"
    assert ctx.get_enrollment_summary()["karma_points"] == 42
    assert ctx.get_course_enrollments() == ["course-a"]
    assert ctx.get_event_enrollments() == ["event-a"]
