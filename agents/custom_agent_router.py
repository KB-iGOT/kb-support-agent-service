# agents/custom_agent_router.py - UPDATED for thread safety

import logging
from typing import List
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.genai import types
from opik import opik_context

from agents.user_profile_info_sub_agent import create_user_profile_info_sub_agent
from agents.user_profile_update_sub_agent import create_user_profile_update_sub_agent
from agents.certificate_issue_sub_agent import create_certificate_issue_sub_agent
from agents.ticket_management_sub_agent import create_ticket_management_sub_agent
from agents.generic_sub_agent import create_generic_sub_agent
from agents.course_progress_sub_agent import create_course_progress_sub_agent
from agents.resource_not_working_sub_agent import create_resource_not_working_sub_agent
from utils.redis_session_service import ChatMessage
from utils.request_context import RequestContext
from utils.prompt_loader import get_prompt

logger = logging.getLogger(__name__)


class KarmayogiCustomerAgent:
    """Custom agent that routes queries to appropriate sub-agents with thread-safe context"""

    def __init__(self, opik_tracer, request_context: RequestContext):
        self.opik_tracer = opik_tracer
        self.request_context = request_context  # Use request context instead of separate params
        self.current_session_id = None

        # Initialize all sub-agents (will be created with context when needed)
        self.user_profile_info_agent = None
        self.user_profile_update_agent = None
        self.certificate_issue_agent = None
        self.ticket_management_agent = None
        self.generic_agent = None
        self.course_progress_agent = None
        self.resource_not_working_agent = None

        # Build chat history context for LLM
        history_context = ""
        chat_history = request_context.chat_history or []
        if chat_history:
            history_context = "\n\nRECENT CONVERSATION HISTORY:\n"
            for msg in chat_history[-6:]:
                role = "User" if msg.role == "user" else "Assistant"
                content = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
                history_context += f"{role}: {content}\n"

        classifier_instruction = get_prompt(
            "custom_agent_router",
            "classifier_instruction",
            history_context=history_context,
        )

        self.classifier_agent = Agent(
            name="karmayogi_intent_classifier",
            model="gemini-2.0-flash-001",
            description="Advanced intent classification agent with conversation context",
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
        self.request_context.session_id = session_id  # Update context too
        logger.info(f"Set session ID in KarmayogiCustomerAgent: {session_id}")

    def _initialize_sub_agents(self):
        """Initialize sub-agents with current request context (THREAD-SAFE)"""
        if not self.user_profile_info_agent:
            self.user_profile_info_agent = create_user_profile_info_sub_agent(
                self.opik_tracer,
                self.request_context  # Pass entire context
            )

        if not self.user_profile_update_agent:
            self.user_profile_update_agent = create_user_profile_update_sub_agent(
                self.opik_tracer,
                self.request_context
            )

        if not self.certificate_issue_agent:
            self.certificate_issue_agent = create_certificate_issue_sub_agent(
                self.opik_tracer,
                self.request_context
            )

        if not self.course_progress_agent:
            self.course_progress_agent = create_course_progress_sub_agent(
                self.opik_tracer,
                self.request_context
            )

        if not self.resource_not_working_agent:
            self.resource_not_working_agent = create_resource_not_working_sub_agent(
                self.opik_tracer,
                self.request_context
            )

        if not self.ticket_management_agent:
            self.ticket_creation_agent = create_ticket_management_sub_agent(
                self.opik_tracer,
                self.request_context
            )

        if not self.generic_agent:
            self.generic_agent = create_generic_sub_agent(
                self.opik_tracer,
                self.request_context
            )

    async def route_query(self, user_message: str, session_service, session_id: str, user_id: str,
                          request_context: RequestContext) -> str:
        """Enhanced routing with thread-safe context"""

        # Update the request context (ensure thread safety)
        self.request_context = request_context

        # Set thread_id for all Opik traces in this conversation
        # Use the Redis session_id (stored in self.current_session_id) as the thread_id
        thread_id = self.current_session_id or request_context.session_id
        try:
            opik_context.update_current_trace(thread_id=thread_id)
            logger.info(f"Set Opik thread_id to: {thread_id}")
        except Exception as e:
            logger.debug(f"Could not set thread_id in route_query: {e}")

        logger.info(f"Routing query with {len(request_context.chat_history or [])} history messages")

        # Initialize sub-agents now that we have session context
        self._initialize_sub_agents()

        # First, handle explicit confirmation for ticket creation after an escalation prompt
        if self._should_force_ticket_creation(user_message, request_context.chat_history or []):
            logger.info("Detected explicit confirmation for ticket creation; routing directly to ticket agent")
            self._initialize_sub_agents()
            adk_session_id = self.current_session_id or request_context.session_id
            return await self._run_sub_agent(
                self.ticket_creation_agent,
                "Create a support ticket for progress issue",
                session_service,
                adk_session_id,
                user_id,
                request_context,
                agent_type="ticket_creation"
            )

        # Build comprehensive context for classification
        classification_context = await self._build_classification_context(
            request_context.get_processing_message(),
            request_context.chat_history or []
        )

        # Use the SAME session_id for all agents to ensure thread_id grouping in Opik
        # The Redis session_id will be used as the ADK session_id and thus as Opik thread_id
        adk_session_id = thread_id  # Use Redis session_id directly
        
        # Check if intent session already exists, if not create it
        existing_intent_session = await session_service.get_session(
            app_name="karmayogi_intent_classifier",
            user_id=user_id,
            session_id=adk_session_id
        )
        
        if existing_intent_session is None:
            await session_service.create_session(
                app_name="karmayogi_intent_classifier",
                user_id=user_id,
                session_id=adk_session_id,
                state={
                    "agent_type": "intent_classifier",
                    "history_count": len(request_context.chat_history or []),
                    "redis_session_id": self.current_session_id
                }
            )
            logger.info(f"Created new intent classification session with unified session_id: {adk_session_id}")
        else:
            logger.info(f"Using existing intent classification session: {adk_session_id}")
        

        content = types.Content(
            role='user',
            parts=[types.Part(text=classification_context)]
        )

        runner = Runner(
            agent=self.classifier_agent,
            app_name="karmayogi_intent_classifier",
            session_service=session_service
        )

        intent_classification = ""

        try:
            async for event in runner.run_async(
                    user_id=user_id,
                    session_id=adk_session_id,
                    new_message=content
            ):
                if hasattr(event, 'content') and event.content:
                    if hasattr(event.content, 'parts') and event.content.parts:
                        for part in event.content.parts:
                            if hasattr(part, 'text') and part.text:
                                intent_classification += part.text

            logger.info(f"Intent classified as: {intent_classification.strip()}")

            # Route to appropriate sub-agent based on classification
            # Use the SAME adk_session_id for all sub-agents to ensure thread_id grouping
            if "USER_PROFILE_INFO" in intent_classification.upper():
                logger.info("Routing to user profile info sub-agent")
                return await self._run_sub_agent(
                    self.user_profile_info_agent,
                    request_context.get_processing_message(),
                    session_service,
                    adk_session_id,  # Use same session_id for thread grouping
                    user_id,
                    request_context,
                    agent_type="user_profile_info"
                )
            elif "USER_PROFILE_UPDATE" in intent_classification.upper():
                logger.info("Routing to user profile update sub-agent")
                return await self._run_sub_agent(
                    self.user_profile_update_agent,
                    request_context.get_processing_message(),
                    session_service,
                    adk_session_id,  # Use same session_id for thread grouping
                    user_id,
                    request_context,
                    agent_type="user_profile_update"
                )
            elif "CERTIFICATE_ISSUES" in intent_classification.upper():
                logger.info("Routing to certificate issue sub-agent")
                return await self._run_sub_agent(
                    self.certificate_issue_agent,
                    request_context.get_processing_message(),
                    session_service,
                    adk_session_id,  # Use same session_id for thread grouping
                    user_id,
                    request_context,
                    agent_type="certificate_issue"
                )
            elif "COURSE_PROGRESS_ISSUE" in intent_classification.upper():
                logger.info("Routing to course progress sub-agent")
                return await self._run_sub_agent(
                    self.course_progress_agent,
                    request_context.get_processing_message(),
                    session_service,
                    adk_session_id,  # Use same session_id for thread grouping
                    user_id,
                    request_context,
                    agent_type="course_progress"
                )
            elif "RESOURCE_NOT_WORKING" in intent_classification.upper():
                logger.info("Routing to resource not working sub-agent")
                return await self._run_sub_agent(
                    self.resource_not_working_agent,
                    request_context.get_processing_message(),
                    session_service,
                    adk_session_id,  # Use same session_id for thread grouping
                    user_id,
                    request_context,
                    agent_type="resource_not_working"
                )
            elif "TICKET_CREATION" in intent_classification.upper():
                logger.info("Routing to ticket creation sub-agent")
                return await self._run_sub_agent(
                    self.ticket_creation_agent,
                    request_context.get_processing_message(),
                    session_service,
                    adk_session_id,  # Use same session_id for thread grouping
                    user_id,
                    request_context,
                    agent_type="ticket_creation"
                )
            else:
                logger.info("Routing to generic sub-agent")
                return await self._run_sub_agent(
                    self.generic_agent,
                    request_context.get_processing_message(),
                    session_service,
                    adk_session_id,  # Use same session_id for thread grouping
                    user_id,
                    request_context,
                    agent_type="generic"
                )

        except Exception as e:
            logger.error(f"Error in intent classification: {e}")
            # Enhanced fallback with conversation context
            route_decision = self._enhanced_fallback_classification(
                request_context.get_processing_message(),
                request_context.chat_history or []
            )

            # Route based on fallback decision... (similar pattern as above)
            return await self._fallback_route(
                route_decision, request_context.get_processing_message(), session_service, session_id, user_id, request_context
            )

    async def _build_classification_context(self, user_message: str, chat_history: List[ChatMessage]) -> str:
        """Build comprehensive context for intent classification (THREAD-SAFE)"""

        # Rephrase query if needed (pass context instead of using globals)
        rephrased_query = await self._rephrase_query_with_context(user_message, chat_history)

        context = f"CURRENT USER MESSAGE: {rephrased_query}\n\n"

        if chat_history:
            context += "RECENT CONVERSATION CONTEXT:\n"
            recent_messages = chat_history[-4:] if len(chat_history) >= 4 else chat_history

            for i, msg in enumerate(recent_messages):
                role = "User" if msg.role == "user" else "Assistant"
                context += f"{role}: {msg.content}\n"

            context += "\nBased on the current message AND the conversation context above, classify the intent.\n"

            # Check conversation context for classification hints
            recent_content = " ".join([msg.content.lower() for msg in recent_messages[-2:]])

            if any(indicator in recent_content for indicator in
                   ["karma", "points", "my", "course", "progress", "enrollment"]):
                context += "\nNOTE: Recent conversation involved personal user data. Consider contextual follow-up questions as USER_PROFILE_INFO.\n"

            if any(indicator in recent_content for indicator in
                   ["change", "update", "modify", "otp", "verify", "profile update"]):
                context += "\nNOTE: Recent conversation involved profile updates. Consider related follow-up questions as USER_PROFILE_UPDATE.\n"

            if any(indicator in recent_content for indicator in
                   ["certificate", "cert", "missing", "wrong", "qr", "not received"]):
                context += "\nNOTE: Recent conversation involved certificate issues. Consider related follow-up questions as CERTIFICATE_ISSUES.\n"

            if any(indicator in recent_content for indicator in
                   ["ticket", "support", "complaint", "help", "escalate", "human", "frustrated"]):
                context += "\nNOTE: Recent conversation involved support requests. Consider related follow-up questions as TICKET_CREATION.\n"

        return context

    async def _rephrase_query_with_context(self, user_message: str, chat_history: List[ChatMessage]) -> str:
        """Rephrase query with context (THREAD-SAFE version)"""
        # Import here to avoid circular imports
        from utils.common_utils import rephrase_query_with_history

        if len(user_message.split()) < 4:
            return await rephrase_query_with_history(user_message, chat_history)
        else:
            return user_message

    async def _run_sub_agent(self, agent: Agent, user_message: str, session_service, session_id: str,
                             user_id: str, request_context: RequestContext, agent_type: str = "unknown") -> str:
        """Run a sub-agent and return the response (THREAD-SAFE)"""

        # Ensure sub-agent traces use the same thread_id as the main conversation
        thread_id = self.current_session_id or request_context.session_id
        try:
            opik_context.update_current_trace(thread_id=thread_id)
        except Exception as e:
            logger.debug(f"Could not set thread_id in _run_sub_agent: {e}")

        logger.info(f"Running {agent.name} ({agent_type}) with {len(request_context.chat_history or [])} history messages")

        # Create session for the sub-agent (using SAME session_id for thread grouping)
        existing_sub_agent_session = await session_service.get_session(
            app_name=f"karmayogi_{agent.name}",
            user_id=user_id,
            session_id=session_id
        )
        
        if existing_sub_agent_session is None:
            await session_service.create_session(
                app_name=f"karmayogi_{agent.name}",
                user_id=user_id,
                session_id=session_id,
                state={
                    "agent_type": agent_type,  # Track which agent is being used
                    "chat_history_count": len(request_context.chat_history or []),
                    "has_conversation_context": len(request_context.chat_history or []) > 0,
                    "redis_session_id": self.current_session_id,
                    "request_context": request_context.to_dict()  # Pass context in state
                }
            )
            logger.info(f"Created new sub-agent session ({agent_type}) for {agent.name} with unified session_id: {session_id}")
        else:
            logger.info(f"Using existing sub-agent session ({agent_type}) for {agent.name}: {session_id}")

        # Enhance user message with rephrased query
        rephrased_query = await self._rephrase_query_with_context(
            request_context.get_processing_message(),
            request_context.chat_history or []
        )

        enhanced_message = f"{rephrased_query}"

        content = types.Content(
            role='user',
            parts=[types.Part(text=enhanced_message)]
        )

        runner = Runner(
            agent=agent,
            app_name=f"karmayogi_{agent.name}",
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

            logger.info(f"Sub-agent {agent.name} completed with response length: {len(response)}")

        except Exception as e:
            logger.error(f"Error running sub-agent {agent.name}: {e}")
            if request_context.chat_history:
                response = "I apologize, but I'm experiencing technical difficulties. Based on our conversation, please try rephrasing your request."
            else:
                response = "I apologize, but I'm experiencing technical difficulties. Please try your request again."

        return response

    def _enhanced_fallback_classification(self, user_message: str, chat_history: List[ChatMessage]) -> str:
        """Enhanced fallback classification with six-way routing including ticket creation"""

        # Check for ticket creation keywords first (highest priority for support requests)
        ticket_keywords = [
            "create ticket", "raise ticket", "support request", "complaint", "escalate",
            "human help", "contact support", "speak to someone", "manager", "supervisor",
            "frustrated", "not working", "broken", "issue", "problem", "help me",
            "support team", "file complaint", "open ticket", "need assistance"
        ]

        # Check for profile update keywords
        profile_update_keywords = [
            "change my name", "update email", "change mobile", "update mobile", "change email",
            "update my", "modify my", "otp", "verify", "send otp", "generate otp"
        ]

        # Check for certificate issue keywords
        certificate_keywords = [
            "certificate", "cert", "missing", "wrong name", "incorrect name", "qr code",
            "not received", "haven't received", "didn't get", "certificate problem",
            "certificate issue", "certificate not working", "certificate format"
        ]

        # Check for course/event progress issues
        course_progress_keywords = [
            "progress", "100%", "stuck", "99%", "module", "pending", "completion", "complete the course",
            "in progress", "not able to complete", "unable to complete"
        ]

        # Check for resource not working
        resource_not_working_keywords = [
            "content not playing", "resource not working", "content is not working", "video not playing",
            "audio not playing", "unable to play", "unplayable", "resource issue", "content issue"
        ]

        # Direct personal keywords
        personal_keywords = ["my", "me", "i", "progress", "karma", "enrollment", "course", "event"]

        # Check for ticket creation requests (highest priority)
        if any(keyword in user_message.lower() for keyword in ticket_keywords):
            return "TICKET_CREATION"

        # Check for profile update requests
        if any(keyword in user_message.lower() for keyword in profile_update_keywords):
            return "USER_PROFILE_UPDATE"

        # Check for certificate issues
        if any(keyword in user_message.lower() for keyword in certificate_keywords):
            return "CERTIFICATE_ISSUES"

        # Check for resource not working issues
        if any(keyword in user_message.lower() for keyword in resource_not_working_keywords):
            return "RESOURCE_NOT_WORKING"

        # Check for course progress issues
        if any(keyword in user_message.lower() for keyword in course_progress_keywords):
            return "COURSE_PROGRESS_ISSUE"

        # Check for personal data queries
        if any(keyword in user_message.lower() for keyword in personal_keywords):
            return "USER_PROFILE_INFO"

        # Contextual personal queries (follow-up questions)
        contextual_queries = ["how many", "do i have", "what about", "show me", "what's my", "how much"]
        is_contextual = any(query in user_message.lower() for query in contextual_queries)

        if is_contextual and chat_history:
            # Check if recent conversation was about personal topics
            recent_content = " ".join([msg.content.lower() for msg in chat_history[-3:]])

            # Check for ticket creation context
            if any(topic in recent_content for topic in ticket_keywords):
                logger.info(f"Contextual ticket creation query detected: '{user_message}' after support discussion")
                return "TICKET_CREATION"

            # Check for certificate context
            if any(topic in recent_content for topic in certificate_keywords):
                logger.info(f"Contextual certificate query detected: '{user_message}' after certificate discussion")
                return "CERTIFICATE_ISSUES"

            # Check for personal data context
            personal_topics = ["karma", "points", "course", "progress", "enrollment", "learning"]
            if any(topic in recent_content for topic in personal_topics):
                logger.info(f"Contextual personal query detected: '{user_message}' after personal topic discussion")
                return "USER_PROFILE_INFO"

        # Default to general support
        return "GENERAL_SUPPORT"

    def _should_force_ticket_creation(self, user_message: str, chat_history: List[ChatMessage]) -> bool:
        """Detect a simple 'yes' confirmation right after we offered ticket creation.

        If the last assistant message offered to create a support ticket and current user says
        'yes' (or similar), force route to ticket creation to avoid classifier ambiguity.
        """
        try:
            if not user_message:
                return False
            msg = user_message.strip().lower()
            yes_tokens = {"yes", "y", "please do", "proceed", "go ahead", "create ticket", "create a ticket"}
            if msg not in yes_tokens:
                return False

            # Look back a few assistant messages for the offer
            offer_keywords = ["create a support ticket", "create a ticket", "support ticket"]
            for m in reversed(chat_history[-4:]):
                if m.role != "assistant":
                    continue
                content_lower = (m.content or "").lower()
                if any(k in content_lower for k in offer_keywords):
                    return True
            return False
        except Exception:
            return False

    async def _fallback_route(self, route_decision: str, user_message: str, session_service,
                              session_id: str, user_id: str, request_context: RequestContext) -> str:
        """Handle fallback routing - uses same session_id for thread grouping"""
        # Use the same session_id (which is adk_session_id = thread_id) for all fallback routing
        if route_decision == "USER_PROFILE_INFO":
            return await self._run_sub_agent(
                self.user_profile_info_agent, user_message, session_service,
                session_id, user_id, request_context, agent_type="user_profile_info"
            )
        elif route_decision == "USER_PROFILE_UPDATE":
            return await self._run_sub_agent(
                self.user_profile_update_agent, user_message, session_service,
                session_id, user_id, request_context, agent_type="user_profile_update"
            )
        elif route_decision == "CERTIFICATE_ISSUES":
            return await self._run_sub_agent(
                self.certificate_issue_agent, user_message, session_service,
                session_id, user_id, request_context, agent_type="certificate_issue"
            )
        elif route_decision == "COURSE_PROGRESS_ISSUE":
            return await self._run_sub_agent(
                self.course_progress_agent, user_message, session_service,
                session_id, user_id, request_context, agent_type="course_progress"
            )
        elif route_decision == "RESOURCE_NOT_WORKING":
            return await self._run_sub_agent(
                self.resource_not_working_agent, user_message, session_service,
                session_id, user_id, request_context, agent_type="resource_not_working"
            )
        elif route_decision == "TICKET_CREATION":
            return await self._run_sub_agent(
                self.ticket_creation_agent, user_message, session_service,
                session_id, user_id, request_context, agent_type="ticket_creation"
            )
        else:
            return await self._run_sub_agent(
                self.generic_agent, user_message, session_service,
                session_id, user_id, request_context, agent_type="generic"
            )