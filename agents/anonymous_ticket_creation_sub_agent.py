# agents/anonymous_ticket_support_sub_agent.py
import logging
from typing import List, Dict, Any

from google.adk.agents import Agent

from utils.redis_session_service import ChatMessage
from utils.request_context import RequestContext

logger = logging.getLogger(__name__)



# Wrapper function for tool compatibility
def create_anonymous_support_ticket_tool() -> str:
    """
    Synchronous wrapper for the async ticket creation function
    Returns JSON string for compatibility with Agent tools
    """

    return "Please contact us for discussions and queries between 9 AM to 5 PM from Monday to Friday on Teams link [https://teams.microsoft.com/l/meetup-join/19%3ameeting_M2Y3ZDE2ZDMtMWQwYS00OWQzLWE3NDctNDRkNTdjOGI4Yzll%40thread.v2/0?context=%7b%22Tid%22%3a%2240cfb65c-9b71-435f-8bc2-bc2c69df1aca%22%2c%22Oid%22%3a%22cbd37bc9-5c33-401f-b590-9decb3c370f8%22%7d] or email us [mission.karmayogi@gov.in]"


def create_anonymous_ticket_support_sub_agent(opik_tracer, request_context: RequestContext) -> Agent:
    """
    Create a specialized sub-agent for handling support ticket requests for anonymous/guest users
    """

    agent_instruction = f"""You are a specialized support guidance assistant for anonymous/guest users of the Karmayogi Bharat platform.

USER STATUS: Anonymous/Guest User (Not Logged In)

CRITICAL: Do not ask for user details like name, email, mobile number or more information about the issue faced. Respond with following message:
'Please contact us for discussions and queries between 9 AM to 5 PM from Monday to Friday on Teams link [https://teams.microsoft.com/l/meetup-join/19%3ameeting_M2Y3ZDE2ZDMtMWQwYS00OWQzLWE3NDctNDRkNTdjOGI4Yzll%40thread.v2/0?context=%7b%22Tid%22%3a%2240cfb65c-9b71-435f-8bc2-bc2c69df1aca%22%2c%22Oid%22%3a%22cbd37bc9-5c33-401f-b590-9decb3c370f8%22%7d] or email us [mission.karmayogi@gov.in]'

🎯 PRIMARY GOAL: Help anonymous users about how to get support for their issues.
"""

    # Build chat history context for LLM
    history_context = ""
    chat_history = request_context.chat_history or []
    if chat_history:
        history_context = "\n\nRECENT CONVERSATION HISTORY:\n"
        for msg in chat_history[-6:]:
            role = "User" if msg.role == "user" else "Assistant"
            content = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
            history_context += f"{role}: {content}\n"

    user_name = "Guest"
    if request_context.user_context and not request_context.is_anonymous:
        user_name = request_context.user_context.get('profile', {}).get('firstName', 'User')

    return Agent(
        name="anonymous_ticket_support_sub_agent",
        model="gemini-2.0-flash-001",
        description="Specialized agent for responding to support requests for anonymous users",
        instruction=agent_instruction,
        tools=[create_anonymous_support_ticket_tool],
        before_agent_callback=opik_tracer.before_agent_callback,
        after_agent_callback=opik_tracer.after_agent_callback,
        before_model_callback=opik_tracer.before_model_callback,
        after_model_callback=opik_tracer.after_model_callback,
    )