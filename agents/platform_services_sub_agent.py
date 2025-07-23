# agents/platform_services_sub_agent.py
import logging
from typing import Dict, List
from google.adk.agents import Agent
from opik import track

logger = logging.getLogger(__name__)


# Placeholder tools for future implementation
@track(name="certificate_issue_tool")
async def certificate_issue_tool(user_message: str) -> dict:
    """Tool for handling certificate-related issues"""
    try:
        logger.info("Handling certificate issue")

        # Import global variables from main module
        from main import user_context, current_chat_history, _rephrase_query_with_history, _call_local_llm

        if not user_context:
            return {"success": False, "error": "User context not available"}

        # Build chat history context
        history_context = ""
        if current_chat_history:
            history_context = "\n\nRECENT CONVERSATION HISTORY:\n"
            for msg in current_chat_history[-6:]:
                role = "User" if msg.role == "user" else "Assistant"
                content = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
                history_context += f"{role}: {content}\n"
            history_context += "\nUse this context to provide more relevant responses.\n"

        # Rephrase query if needed
        print(f"Original User message for certificate_issue_tool: {user_message}")
        if len(user_message.split()) < 4:
            rephrased_query = await _rephrase_query_with_history(user_message, current_chat_history)
        else:
            rephrased_query = user_message
        print(f"Rephrased User message for certificate_issue_tool: {rephrased_query}")

        # Extract user info
        profile_data = user_context.get('profile', {})
        enrollment_summary = user_context.get('enrollment_summary', {})
        user_name = profile_data.get('firstName', 'User')

        system_message = f"""
## Role and Context
You are a specialized support agent for Karmayogi Bharat platform certificate issues. Handle all certificate-related problems with empathy and clear guidance.

## User Information
- Name: {user_name}
- Total Certificates Earned: {enrollment_summary.get('certified_courses_count', 0)} courses + {enrollment_summary.get('certified_events_count', 0)} events
- Total Learning Progress: {enrollment_summary.get('total_courses_completed', 0)} courses completed, {enrollment_summary.get('total_events_completed', 0)} events completed

## Your Responsibilities
Handle certificate-related issues including:
- Missing certificates
- Incorrect names on certificates
- QR code issues
- Certificate format problems
- Certificate re-issuance requests

## Previous Context
{history_context}

## Response Guidelines
- Be empathetic - certificate issues can be frustrating
- Provide step-by-step guidance for resolution
- Explain the certificate verification process
- Offer multiple resolution paths when possible
- Create support tickets for complex issues
- Set realistic expectations for resolution time

## Current Certificate Issue
The user is reporting: {rephrased_query}

Based on the user's issue, provide helpful guidance for certificate problems. If the issue cannot be resolved through self-service, create a support ticket with proper escalation.
"""

        response = await _call_local_llm(system_message, rephrased_query)

        return {
            "success": True,
            "response": response,
            "data_type": "certificate_issue"
        }

    except Exception as e:
        logger.error(f"Error in certificate_issue_tool: {e}")
        return {"success": False, "error": str(e)}


@track(name="platform_service_request_tool")
async def platform_service_request_tool(user_message: str) -> dict:
    """Tool for handling general platform service requests"""
    try:
        logger.info("Handling platform service request")

        # Import global variables from main module
        from main import user_context, current_chat_history, _rephrase_query_with_history, _call_local_llm

        if not user_context:
            return {"success": False, "error": "User context not available"}

        # Build chat history context
        history_context = ""
        if current_chat_history:
            history_context = "\n\nRECENT CONVERSATION HISTORY:\n"
            for msg in current_chat_history[-6:]:
                role = "User" if msg.role == "user" else "Assistant"
                content = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
                history_context += f"{role}: {content}\n"
            history_context += "\nUse this context to provide more relevant responses.\n"

        # Rephrase query if needed
        print(f"Original User message for platform_service_request_tool: {user_message}")
        if len(user_message.split()) < 4:
            rephrased_query = await _rephrase_query_with_history(user_message, current_chat_history)
        else:
            rephrased_query = user_message
        print(f"Rephrased User message for platform_service_request_tool: {rephrased_query}")

        # Extract user info
        profile_data = user_context.get('profile', {})
        user_name = profile_data.get('firstName', 'User')

        system_message = f"""
## Role and Context
You are a specialized support agent for Karmayogi Bharat platform service requests. Handle various platform service needs with professionalism and efficiency.

## User Information
- Name: {user_name}
- User ID: {profile_data.get('identifier', 'Unknown')}
- Email: {profile_data.get('email', 'Unknown')}

## Your Responsibilities
Handle platform service requests including:
- Account access issues
- Technical support needs
- Administrative inquiries
- Policy questions
- General platform help
- Support ticket creation

## Previous Context
{history_context}

## Response Guidelines
- Be professional and helpful
- Provide step-by-step guidance
- Escalate complex issues appropriately
- Create support tickets when needed
- Set realistic expectations
- Offer multiple resolution paths

## Current Service Request
The user is requesting: {rephrased_query}

Based on the user's request, provide appropriate assistance or escalate to the right support channel.
"""

        response = await _call_local_llm(system_message, rephrased_query)

        return {
            "success": True,
            "response": response,
            "data_type": "platform_service"
        }

    except Exception as e:
        logger.error(f"Error in platform_service_request_tool: {e}")
        return {"success": False, "error": str(e)}


def create_platform_services_sub_agent(opik_tracer, current_chat_history, user_context) -> Agent:
    """Create the platform services sub-agent for handling service requests except profile updates"""

    tools = [
        certificate_issue_tool,
        platform_service_request_tool
    ]

    # Build chat history context for LLM
    history_context = ""
    if current_chat_history:
        history_context = "\n\nRECENT CONVERSATION HISTORY:\n"
        for msg in current_chat_history[-6:]:  # Last 3 exchanges (6 messages)
            role = "User" if msg.role == "user" else "Assistant"
            content = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
            history_context += f"{role}: {content}\n"
        history_context += "\nUse this context to provide more relevant and personalized responses.\n"

    user_name = user_context.get('profile', {}).get('firstName', 'User') if user_context else 'User'

    agent = Agent(
        name="platform_services_sub_agent",
        model="gemini-2.0-flash-001",
        description="Specialized agent for handling platform service requests including certificate issues and general platform services (excluding profile updates)",
        instruction=f"""
You are a specialized sub-agent that handles platform service requests for Karmayogi Bharat platform including:

## Your Primary Responsibilities:

### 1. CERTIFICATE ISSUES (use certificate_issue_tool)
Handle all certificate-related problems:
- **Missing certificates**: "I didn't get my certificate", "Certificate not received"
- **Incorrect names on certificates**: "Wrong name on certificate", "Name is incorrect in certificate"
- **QR code issues**: "QR code is missing", "Certificate QR code problem"
- **Certificate format problems**: "Certificate is not correct", "Certificate format issue"
- **Certificate re-issuance**: Any request to re-issue or fix certificates

### 2. GENERAL PLATFORM SERVICES (use platform_service_request_tool)
Handle other platform service requests:
- **Account access issues**: Login problems, password reset, account locked
- **Technical support**: Platform functionality problems, navigation issues
- **Administrative requests**: Policy inquiries, general platform questions
- **Support ticket creation**: Complex issues requiring human intervention

## Tool Selection Guidelines:

**Use certificate_issue_tool when user mentions:**
- Certificate problems (missing, incorrect, format issues)
- QR code problems on certificates
- Certificate re-issuance requests
- Name corrections on certificates
- Certificate delivery issues

**Use platform_service_request_tool for:**
- Account access problems
- Technical support needs
- General platform help
- Administrative inquiries
- Complex issues requiring escalation

## Response Approach:
- **Be empathetic and professional** - Users may be frustrated with issues
- **Follow established workflows** - Each service type has specific procedures
- **Provide step-by-step guidance** - Break down complex processes
- **Use conversation history** - Avoid repetition and provide contextual responses
- **Prioritize security** - Always verify user identity for sensitive operations
- **Escalate when needed** - Create support tickets for complex issues
- **Set realistic expectations** - Provide accurate timelines and next steps

## Security and Verification:
- Verify course enrollment before handling certificate issues
- Protect user privacy and sensitive information
- Follow platform security protocols

## User Experience Principles:
- Acknowledge user frustration with empathy
- Provide clear, actionable next steps
- Explain why certain steps are necessary (security, verification)
- Offer alternatives when primary methods don't work
- Keep users informed throughout the process

## Conversation Context:
User's name: {user_name}

{history_context}

## Important Notes:
- This agent handles service requests EXCEPT profile updates (that's handled by user_profile_update_sub_agent)
- Always verify user identity before proceeding with sensitive operations
- Create support tickets for issues that can't be resolved through self-service
- Provide contact information for escalation when needed

Select the appropriate tool based on the user's specific request and provide comprehensive, helpful assistance following the established workflows.
""",
        tools=tools,
        before_agent_callback=opik_tracer.before_agent_callback,
        after_agent_callback=opik_tracer.after_agent_callback,
        before_model_callback=opik_tracer.before_model_callback,
        after_model_callback=opik_tracer.after_model_callback,
        before_tool_callback=opik_tracer.before_tool_callback,
        after_tool_callback=opik_tracer.after_tool_callback,
    )

    return agent