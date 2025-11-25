# agents/anonymous_customer_agent_router.py - FIXED VERSION (THREAD-SAFE)
import logging
from typing import List
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.genai import types

from agents.anonymous_ticket_support_sub_agent import create_anonymous_ticket_support_sub_agent
from agents.generic_sub_agent import create_generic_sub_agent
from utils.redis_session_service import ChatMessage
from utils.request_context import RequestContext  # ✅ ADD THIS IMPORT
from utils.prompt_loader import get_prompt

logger = logging.getLogger(__name__)

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
        classifier_instruction = get_prompt(
            "anonymous_customer_agent_router",
            "classifier_instruction",
        )
        self.classifier_agent = Agent(
            name="anonymous_intent_classifier",
            model="gemini-2.0-flash-001",
            description="Intent classification for anonymous/guest users",
            instruction=classifier_instruction,
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
        
        # Check if anonymous intent session already exists, if not create it
        existing_intent_session = await session_service.get_session(
            app_name="anonymous_intent_classifier",
            user_id=user_id,
            session_id=intent_session_id
        )
        
        if existing_intent_session is None:
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
            logger.info(f"Created new anonymous intent classification session: {intent_session_id}")
        else:
            logger.info(f"Using existing anonymous intent classification session: {intent_session_id}")

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
        existing_sub_agent_session = await session_service.get_session(
            app_name=f"anonymous_{agent.name}",
            user_id=user_id,
            session_id=session_id
        )
        
        if existing_sub_agent_session is None:
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
            logger.info(f"Created new anonymous sub-agent session for {agent.name}: {session_id}")
        else:
            logger.info(f"Using existing anonymous sub-agent session for {agent.name}: {session_id}")

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