# agents/anonymous_customer_agent_router.py - FIXED VERSION (THREAD-SAFE)
import logging
from typing import List
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.genai import types

from agents.anonymous_ticket_creation_sub_agent import create_anonymous_ticket_support_sub_agent
from agents.generic_sub_agent import create_generic_sub_agent
from utils.redis_session_service import ChatMessage
from utils.request_context import RequestContext  # ✅ ADD THIS IMPORT

logger = logging.getLogger(__name__)

# IMPROVED classification instruction for anonymous users
ANONYMOUS_CLASSIFIER_INSTRUCTION = """
You are an intent classifier for Karmayogi Bharat platform queries from non-logged in users.

AVAILABLE CLASSIFICATIONS FOR ANONYMOUS USERS:

1. **GENERAL_SUPPORT** - For informational queries about platform features and how-to questions
   - Questions starting with "How do I...", "How to...", "What is...", "Where can I..."
   - Platform features, functionality, navigation help
   - Profile management instructions (how to update details)
   - Learning and course information
   - Certificate download instructions
   - Karma points information
   - General platform policies and procedures
   - Technical guidance that doesn't indicate a current problem

2. **TICKET_SUPPORT** - For actual support requests when users have problems or need assistance
   - Explicit requests for help: "I need help", "Create a ticket", "Contact support"
   - Current problems: "I can't access", "I'm unable to", "It's not working"
   - Error reports: "I'm getting an error", "Something is broken"
   - Account issues: "My account is locked", "I forgot my password"
   - Registration problems: "I can't register", "Registration failed"

IMPORTANT DISTINCTION:
- "How do I update my phone number?" → GENERAL_SUPPORT (asking for instructions)
- "Why I am not able to receive the OTP?" → GENERAL_SUPPORT (asking for information)
- "I forgot my password" → GENERAL_SUPPORT (asking for information)
- "I am unable to login with parichay" → GENERAL_SUPPORT (asking for information)
- "I can't update my phone number" → TICKET_SUPPORT (reporting a problem)
- "What are the steps to download certificate?" → GENERAL_SUPPORT (asking for information)
- "My certificate download is not working" → TICKET_SUPPORT (reporting an issue)

EXAMPLES FOR ANONYMOUS USERS:
- "What is Karmayogi Bharat?" → GENERAL_SUPPORT
- "How do I register?" → GENERAL_SUPPORT
- "How do I update my phone number?" → GENERAL_SUPPORT
- "How to download certificates?" → GENERAL_SUPPORT
- "What are Karma points?" → GENERAL_SUPPORT
- "Steps to change password?" → GENERAL_SUPPORT
- "I can't access the platform" → TICKET_SUPPORT
- "I need help with registration" → TICKET_SUPPORT
- "My account is not working" → TICKET_SUPPORT
- "Create a support ticket" → TICKET_SUPPORT

Respond with only: GENERAL_SUPPORT or TICKET_SUPPORT
"""


# ✅ FIXED: Anonymous Customer Agent Class (THREAD-SAFE)
class AnonymousKarmayogiCustomerAgent:
    """Custom agent for anonymous/non-logged in users with thread-safe context"""

    def __init__(self, opik_tracer, request_context: RequestContext):  # ✅ FIXED: Accept RequestContext
        self.opik_tracer = opik_tracer
        self.request_context = request_context  # ✅ FIXED: Use RequestContext instead of separate params
        self.current_session_id = None

        # Only initialize agents available to anonymous users
        self.TICKET_SUPPORT_agent = None
        self.generic_agent = None

        # Improved classifier for anonymous users
        self.classifier_agent = Agent(
            name="anonymous_intent_classifier",
            model="gemini-2.0-flash-001",
            description="Intent classification for anonymous/guest users",
            instruction=ANONYMOUS_CLASSIFIER_INSTRUCTION,
            tools=[],
            before_agent_callback=opik_tracer.before_agent_callback,
            after_agent_callback=opik_tracer.after_agent_callback,
            before_model_callback=opik_tracer.before_model_callback,
            after_model_callback=opik_tracer.after_model_callback,
        )

    def set_session_id(self, session_id: str):
        """Set the current session ID for sub-agents"""
        self.current_session_id = session_id
        self.request_context.session_id = session_id  # ✅ FIXED: Update context too
        logger.info(f"Set session ID in AnonymousKarmayogiCustomerAgent: {session_id}")

    def _initialize_sub_agents(self):
        """Initialize sub-agents available to anonymous users (THREAD-SAFE)"""
        if not self.TICKET_SUPPORT_agent:
            self.TICKET_SUPPORT_agent = create_anonymous_ticket_support_sub_agent(
                self.opik_tracer,
                self.request_context  # ✅ FIXED: Pass RequestContext instead of separate params
            )

        if not self.generic_agent:
            self.generic_agent = create_generic_sub_agent(
                self.opik_tracer,
                self.request_context  # ✅ FIXED: Pass RequestContext instead of separate params
            )

    async def route_query(self, user_message: str, session_service, session_id: str, user_id: str,
                          request_context: RequestContext) -> str:  # ✅ FIXED: Accept RequestContext
        """Improved routing for anonymous users with thread-safe context"""

        # ✅ FIXED: Update the request context (ensure thread safety)
        self.request_context = request_context

        current_chat_history = self.request_context.chat_history or []
        logger.info(f"Routing anonymous user query with {len(current_chat_history)} history messages")

        self._initialize_sub_agents()

        # Build context for classification
        classification_context = await self._build_anonymous_classification_context(request_context.get_processing_message(), current_chat_history)

        # Create session for intent classification
        intent_session_id = f"anonymous_intent_{session_id}"
        await session_service.create_session(
            app_name="anonymous_intent_classifier",
            user_id=user_id,
            session_id=intent_session_id,
            state={
                "history_count": len(current_chat_history),
                "is_anonymous": True,
                "request_context": request_context.to_dict()  # ✅ FIXED: Pass context in state
            }
        )

        content = types.Content(
            role='user',
            parts=[types.Part(text=classification_context)]
        )

        runner = Runner(
            agent=self.classifier_agent,
            app_name="anonymous_intent_classifier",
            session_service=session_service
        )

        intent_classification = ""

        try:
            async for event in runner.run_async(
                    user_id=user_id,
                    session_id=intent_session_id,
                    new_message=content
            ):
                if hasattr(event, 'content') and event.content:
                    if hasattr(event.content, 'parts') and event.content.parts:
                        for part in event.content.parts:
                            if hasattr(part, 'text') and part.text:
                                intent_classification += part.text

            logger.info(f"Anonymous user intent classified as: {intent_classification.strip()}")

            # Route to appropriate sub-agent
            if "TICKET_SUPPORT" in intent_classification.upper():
                logger.info("Routing anonymous user to ticket creation sub-agent")
                return await self._run_sub_agent(
                    self.TICKET_SUPPORT_agent,
                    request_context.get_processing_message(),
                    session_service,
                    f"anonymous_ticket_{session_id}",
                    user_id,
                    request_context  # ✅ FIXED: Pass RequestContext
                )
            else:
                logger.info("Routing anonymous user to generic sub-agent")
                return await self._run_sub_agent(
                    self.generic_agent,
                    request_context.get_processing_message(),
                    session_service,
                    f"anonymous_generic_{session_id}",
                    user_id,
                    request_context  # ✅ FIXED: Pass RequestContext
                )

        except Exception as e:
            logger.error(f"Error in anonymous user intent classification: {e}")
            # Improved fallback logic for anonymous users
            route_decision = self._enhanced_fallback_classification(request_context.get_processing_message(), current_chat_history)

            if route_decision == "TICKET_SUPPORT":
                logger.info("Fallback: routing anonymous user to ticket creation")
                return await self._run_sub_agent(
                    self.TICKET_SUPPORT_agent,
                    request_context.get_processing_message(),
                    session_service,
                    f"anonymous_ticket_{session_id}",
                    user_id,
                    request_context  # ✅ FIXED: Pass RequestContext
                )
            else:
                logger.info("Fallback: routing anonymous user to general support")
                return await self._run_sub_agent(
                    self.generic_agent,
                    request_context.get_processing_message(),
                    session_service,
                    f"anonymous_generic_{session_id}",
                    user_id,
                    request_context  # ✅ FIXED: Pass RequestContext
                )

    def _enhanced_fallback_classification(self, user_message: str, chat_history: List[ChatMessage]) -> str:
        """Enhanced fallback logic for anonymous users (THREAD-SAFE)"""
        problem_keywords = [
            "can't", "cannot", "unable", "not working", "error", "failed",
            "broken", "issue", "problem", "help me", "i need help",
            "create ticket", "contact support", "assistance needed"
        ]

        informational_keywords = [
            "how do i", "how to", "what is", "what are", "where can i",
            "steps to", "guide to", "instructions", "explain", "tell me about"
        ]

        user_message_lower = user_message.lower()

        # Check for informational queries first
        if any(keyword in user_message_lower for keyword in informational_keywords):
            return "GENERAL_SUPPORT"
        # Then check for problem statements
        elif any(keyword in user_message_lower for keyword in problem_keywords):
            return "TICKET_SUPPORT"
        else:
            # Default to general support for anonymous users
            return "GENERAL_SUPPORT"

    async def _build_anonymous_classification_context(self, user_message: str, chat_history: List[ChatMessage]) -> str:
        """Build context for anonymous user classification (THREAD-SAFE)"""

        # Rephrase query if needed (using context, not globals)
        rephrased_query = await self._rephrase_query_with_context(user_message, chat_history)

        context = f"ANONYMOUS USER MESSAGE: {rephrased_query}\n\n"
        context += "USER STATUS: Anonymous/Guest (not logged in)\n"
        context += "AVAILABLE SERVICES: General platform information and support ticket creation only\n\n"

        if chat_history:
            context += "RECENT CONVERSATION CONTEXT:\n"
            recent_messages = chat_history[-4:] if len(chat_history) >= 4 else chat_history

            for i, msg in enumerate(recent_messages):
                role = "User" if msg.role == "user" else "Assistant"
                context += f"{role}: {msg.content[:150]}...\n"

            context += "\nClassify this anonymous user's intent for appropriate routing.\n"

        return context

    async def _rephrase_query_with_context(self, user_message: str, chat_history: List[ChatMessage]) -> str:
        """Rephrase query with context (THREAD-SAFE version)"""
        try:
            # Import here to avoid circular imports
            from utils.common_utils import rephrase_query_with_history

            if len(user_message.split()) < 4:
                return await rephrase_query_with_history(user_message, chat_history)
            else:
                return user_message
        except Exception as e:
            logger.error(f"Error rephrasing query: {e}")
            return user_message

    async def _run_sub_agent(self, agent: Agent, user_message: str, session_service, session_id: str,
                             user_id: str, request_context: RequestContext) -> str:  # ✅ FIXED: Accept RequestContext
        """Run a sub-agent for anonymous users (THREAD-SAFE)"""

        current_chat_history = request_context.chat_history or []
        logger.info(f"Running {agent.name} for anonymous user with {len(current_chat_history)} history messages")

        # Create session for the sub-agent
        await session_service.create_session(
            app_name=f"anonymous_{agent.name}",
            user_id=user_id,
            session_id=session_id,
            state={
                "chat_history_count": len(current_chat_history),
                "has_conversation_context": len(current_chat_history) > 0,
                "redis_session_id": self.current_session_id,
                "is_anonymous": True,
                "request_context": request_context.to_dict()  # ✅ FIXED: Pass context in state
            }
        )

        # Enhance user message with rephrased query
        rephrased_query = await self._rephrase_query_with_context(request_context.get_processing_message(), current_chat_history)
        enhanced_message = f"{rephrased_query}"

        content = types.Content(
            role='user',
            parts=[types.Part(text=enhanced_message)]
        )

        runner = Runner(
            agent=agent,
            app_name=f"anonymous_{agent.name}",
            session_service=session_service
        )

        response = ""

        try:
            async for event in runner.run_async(
                    user_id=user_id,
                    session_id=session_id,
                    new_message=content
            ):
                if hasattr(event, 'content') and event.content:
                    if hasattr(event.content, 'parts') and event.content.parts:
                        for part in event.content.parts:
                            if hasattr(part, 'text') and part.text:
                                response += part.text

            logger.info(f"Anonymous sub-agent {agent.name} completed with response length: {len(response)}")

        except Exception as e:
            logger.error(f"Error running anonymous sub-agent {agent.name}: {e}")
            response = "I apologize, but I'm experiencing technical difficulties. As a guest user, I can help you with platform information and support requests. Please try again."

        return response