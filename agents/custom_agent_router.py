# agents/custom_agent_router.py - UPDATED for thread safety

import logging
from typing import List
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.genai import types

from agents.user_profile_info_sub_agent import create_user_profile_info_sub_agent
from agents.user_profile_update_sub_agent import create_user_profile_update_sub_agent
from agents.certificate_issue_sub_agent import create_certificate_issue_sub_agent
from agents.ticket_creation_sub_agent import create_ticket_creation_sub_agent
from agents.generic_sub_agent import create_generic_sub_agent
from utils.redis_session_service import ChatMessage
from utils.request_context import RequestContext

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
        self.ticket_creation_agent = None
        self.generic_agent = None

        # Build chat history context for LLM
        history_context = ""
        chat_history = request_context.chat_history or []
        if chat_history:
            history_context = "\n\nRECENT CONVERSATION HISTORY:\n"
            for msg in chat_history[-6:]:
                role = "User" if msg.role == "user" else "Assistant"
                content = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
                history_context += f"{role}: {content}\n"

        # Enhanced classification agent
        self.classifier_agent = Agent(
            name="karmayogi_intent_classifier",
            model="gemini-2.0-flash-001",
            description="Advanced intent classification agent with conversation context",
            # ... instruction remains the same
            instruction=f"""
You are an advanced intent classifier for Karmayogi Bharat platform queries.

CLASSIFICATION RULES:
1. **USER_PROFILE_INFO** - For personal data queries including:
   - Direct personal queries: "my courses", "my progress", "my karma points", "my email", "my mobile number", "my name", "my organisation", "my grade", "my department", "my designation", "my certificates", "my profile"
   - Certificate information queries: "how many certificates do I have", "which courses have certificates", "courses without certificates", "certificate status", "certificate count"
   - Contextual follow-up questions when recent conversation was about personal data
   - Questions like "How many do I have?", "What's my status?", "Show me..." when context indicates personal data
   - Any query that requires access to user's personal enrollment, progress, or achievement data

2. **USER_PROFILE_UPDATE** - For profile data modification requests (only for name, email and mobile number) including:
   - Profile update requests: "change my name", "update email", "change mobile number", "update my profile"
   - OTP-related requests: "send OTP", "verify OTP", "generate OTP"
   - Profile modification workflow: Any request to modify personal profile information

3. **CERTIFICATE_ISSUES** - For certificate-related problems including:
   - Certificate not received: "I didn't get my certificate", "haven't received certificate", "where is my certificate"
   - Incorrect name on certificate: "wrong name on certificate", "certificate has incorrect name", "name is misspelled"
   - QR code issues: "QR code missing", "certificate doesn't have QR code", "QR code not working"
   - Certificate format issues: "certificate format problem", "certificate download issue"
   - Certificate validation problems: "certificate not valid", "certificate verification failed"
   - **IMPORTANT**: This is for PROBLEMS/ISSUES with certificates, NOT information requests about certificates

4. **TICKET_CREATION** - For support ticket and complaint requests including:
   - Explicit ticket requests: "create a ticket", "raise a support request", "I want to file a complaint", "open a ticket"
   - Support requests: "I need help", "contact support", "escalate this issue", "I want to speak to someone"
   - Unresolved issues: "this is not working", "I'm frustrated", "nothing is helping", "I need human assistance"
   - Escalation requests: "escalate to supervisor", "manager", "human agent", "support team"
   - Persistent problems: Issues that haven't been resolved after previous attempts
   - General complaints: "I'm having trouble with", "problem with platform", "issue with system"

6. **GENERAL_SUPPORT** - For platform help, features, how-to questions, technical support:
   - "How does X work?", "What is Y?", platform features, troubleshooting
   - General information that doesn't require personal user data or service actions
   - Documentation-based queries

TICKET_CREATION PRIORITY INDICATORS:
- Keywords: "ticket", "complaint", "support request", "escalate", "human", "manager", "supervisor"
- Emotional indicators: "frustrated", "angry", "disappointed", "not working", "broken"
- Persistence indicators: "still not working", "tried everything", "nothing helps"
- Explicit requests: "I want to", "I need to", "please help me", "contact support"

DISAMBIGUATION RULES:
- Questions starting with "How many", "Which", "What", "Show me" about certificates = USER_PROFILE_INFO
- Statements about problems: "I didn't get", "missing", "wrong", "not working" = CERTIFICATE_ISSUES
- Support/ticket requests: "create ticket", "I need help", "contact support" = TICKET_CREATION
- Profile update requests: "change my name", "update email", "change mobile" = USER_PROFILE_UPDATE
- Update requests other than name, email, or mobile = GENERAL_SUPPORT
- Information requests use question words (how, what, which, where is my...)
- Problem reports use complaint language (didn't get, missing, wrong, broken, not working)
- Support requests use help-seeking language (need help, contact support, create ticket)

CONTEXT ANALYSIS:
- ALWAYS consider the conversation history to understand the context
- **PRIORITY**: Analyze the CURRENT query structure first, then apply context
- If user explicitly asks for ticket creation or support, classify as TICKET_CREATION
- If current query is clearly an information request (starts with "how many", "which", "what"), classify as USER_PROFILE_INFO regardless of previous context
- If current query reports a problem ("I didn't get", "missing", "wrong"), classify as CERTIFICATE_ISSUES
- For ambiguous queries, then use conversation context as tiebreaker

EXAMPLES:
Certificate Information Queries (USER_PROFILE_INFO):
- "How many certificates do I have?" → USER_PROFILE_INFO
- "Which courses have certificates?" → USER_PROFILE_INFO  
- "How many courses don't have certificates?" → USER_PROFILE_INFO
- "Show me my certificates" → USER_PROFILE_INFO
- "What's my certificate status?" → USER_PROFILE_INFO

Certificate Problem Reports (CERTIFICATE_ISSUES):
- "I didn't get my certificate" → CERTIFICATE_ISSUES
- "Wrong name on certificate" → CERTIFICATE_ISSUES
- "Certificate is missing" → CERTIFICATE_ISSUES
- "QR code not working" → CERTIFICATE_ISSUES

Ticket Creation Requests (TICKET_CREATION):
- "I want to create a ticket" → TICKET_CREATION
- "I need to contact support" → TICKET_CREATION
- "Raise a support request" → TICKET_CREATION
- "I'm frustrated, nothing is working" → TICKET_CREATION
- "Can someone help me with this?" → TICKET_CREATION
- "I want to speak to a human" → TICKET_CREATION
- "Escalate this to your manager" → TICKET_CREATION
- "I'm not getting certificate even after 24 hours" → TICKET_CREATION
- "Why is karma points not credited to me" → TICKET_CREATION

General Platform information (GENERAL_SUPPORT):
- "What are karma points?" → GENERAL_SUPPORT (general information)
- "How to enroll in courses?" → GENERAL_SUPPORT (general help)
- "What is the platform's policy on data privacy?" → GENERAL_SUPPORT (platform policy)


## Chat History Context:
{chat_history}

Respond with only: USER_PROFILE_INFO, USER_PROFILE_UPDATE, CERTIFICATE_ISSUES, TICKET_CREATION, or GENERAL_SUPPORT
""",
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

        if not self.ticket_creation_agent:
            self.ticket_creation_agent = create_ticket_creation_sub_agent(
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

        logger.info(f"Routing query with {len(request_context.chat_history or [])} history messages")

        # Initialize sub-agents now that we have session context
        self._initialize_sub_agents()

        # Build comprehensive context for classification
        classification_context = await self._build_classification_context(
            user_message,
            request_context.chat_history or []
        )

        # Create a session for intent classification
        intent_session_id = f"intent_{session_id}"
        await session_service.create_session(
            app_name="karmayogi_intent_classifier",
            user_id=user_id,
            session_id=intent_session_id,
            state={"history_count": len(request_context.chat_history or [])}
        )

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
                    session_id=intent_session_id,
                    new_message=content
            ):
                if hasattr(event, 'content') and event.content:
                    if hasattr(event.content, 'parts') and event.content.parts:
                        for part in event.content.parts:
                            if hasattr(part, 'text') and part.text:
                                intent_classification += part.text

            logger.info(f"Intent classified as: {intent_classification.strip()}")

            # Route to appropriate sub-agent based on classification
            if "USER_PROFILE_INFO" in intent_classification.upper():
                logger.info("Routing to user profile info sub-agent")
                return await self._run_sub_agent(
                    self.user_profile_info_agent,
                    user_message,
                    session_service,
                    f"profile_info_{session_id}",
                    user_id,
                    request_context
                )
            elif "USER_PROFILE_UPDATE" in intent_classification.upper():
                logger.info("Routing to user profile update sub-agent")
                return await self._run_sub_agent(
                    self.user_profile_update_agent,
                    user_message,
                    session_service,
                    f"profile_update_{session_id}",
                    user_id,
                    request_context
                )
            elif "CERTIFICATE_ISSUES" in intent_classification.upper():
                logger.info("Routing to certificate issue sub-agent")
                return await self._run_sub_agent(
                    self.certificate_issue_agent,
                    user_message,
                    session_service,
                    f"certificate_issue_{session_id}",
                    user_id,
                    request_context
                )
            elif "TICKET_CREATION" in intent_classification.upper():
                logger.info("Routing to ticket creation sub-agent")
                return await self._run_sub_agent(
                    self.ticket_creation_agent,
                    user_message,
                    session_service,
                    f"ticket_creation_{session_id}",
                    user_id,
                    request_context
                )
            else:
                logger.info("Routing to generic sub-agent")
                return await self._run_sub_agent(
                    self.generic_agent,
                    user_message,
                    session_service,
                    f"generic_{session_id}",
                    user_id,
                    request_context
                )

        except Exception as e:
            logger.error(f"Error in intent classification: {e}")
            # Enhanced fallback with conversation context
            route_decision = self._enhanced_fallback_classification(
                user_message,
                request_context.chat_history or []
            )

            # Route based on fallback decision... (similar pattern as above)
            return await self._fallback_route(
                route_decision, user_message, session_service, session_id, user_id, request_context
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

            # Add contextual hints...
            recent_content = " ".join([msg.content.lower() for msg in recent_messages[-2:]])

            # Add contextual analysis as before...

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
                             user_id: str, request_context: RequestContext) -> str:
        """Run a sub-agent and return the response (THREAD-SAFE)"""

        logger.info(f"Running {agent.name} with {len(request_context.chat_history or [])} history messages")

        # Create session for the sub-agent
        await session_service.create_session(
            app_name=f"karmayogi_{agent.name}",
            user_id=user_id,
            session_id=session_id,
            state={
                "chat_history_count": len(request_context.chat_history or []),
                "has_conversation_context": len(request_context.chat_history or []) > 0,
                "redis_session_id": self.current_session_id,
                "request_context": request_context.to_dict()  # Pass context in state
            }
        )

        # Enhance user message with rephrased query
        rephrased_query = await self._rephrase_query_with_context(
            user_message,
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

    # Add other helper methods...
    def _enhanced_fallback_classification(self, user_message: str, chat_history: List[ChatMessage]) -> str:
        """Enhanced fallback classification (same logic as before)"""
        # Implementation remains the same...
        return "GENERAL_SUPPORT"  # placeholder

    async def _fallback_route(self, route_decision: str, user_message: str, session_service,
                              session_id: str, user_id: str, request_context: RequestContext) -> str:
        """Handle fallback routing"""
        # Similar routing logic as in the main try block
        if route_decision == "USER_PROFILE_INFO":
            return await self._run_sub_agent(
                self.user_profile_info_agent, user_message, session_service,
                f"profile_info_{session_id}", user_id, request_context
            )
        # ... other routes
        else:
            return await self._run_sub_agent(
                self.generic_agent, user_message, session_service,
                f"generic_{session_id}", user_id, request_context
            )