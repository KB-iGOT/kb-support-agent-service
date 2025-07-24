# agents/ticket_creation_sub_agent.py - FIXED VERSION
import json
import logging
from typing import List, Dict, Any
from google.adk.agents import Agent
from google.adk.tools import FunctionTool

from utils.zoho_utils import zoho_desk, ZohoTicketData, ZohoTicketPriority, ZohoIssueCategory
from utils.redis_session_service import ChatMessage

logger = logging.getLogger(__name__)


def create_ticket_creation_sub_agent(opik_tracer, current_chat_history: List[ChatMessage],
                                     user_context: Dict[str, Any]) -> Agent:
    """
    Create a specialized sub-agent for handling support ticket creation requests

    This agent handles:
    - Certificate issues (not received, incorrect name, QR code missing)
    - Karma points issues
    - Profile/account issues
    - Technical support requests
    - General support ticket creation
    """

    profile_data = user_context.get('profile', {})
    user_name = profile_data.get('firstName', 'User')
    user_email = profile_data.get('profileDetails', {}).get('personalDetails', {}).get('primaryEmail', '')
    user_mobile = profile_data.get('profileDetails', {}).get('personalDetails', {}).get('mobile', '')

    # Define the tool function
    def create_support_ticket(issue_type: str, issue_description: str,
                             course_name: str = "", priority: str = "low") -> str:
        """
        Create a support ticket in Zoho Desk

        Args:
            issue_type: Type of issue (certificate_not_received, certificate_incorrect_name,
                       certificate_qr_missing, karma_points, profile_issue, technical_support, general)
            issue_description: Detailed description of the issue
            course_name: Name of the course (if applicable)
            priority: Priority level (low, medium, high, urgent)

        Returns:
            JSON string with ticket creation result
        """
        import asyncio

        async def create_ticket():
            try:
                logger.info(f"Creating support ticket for user: {user_name}, issue: {issue_type}")

                # Map priority string to enum
                priority_map = {
                    "low": ZohoTicketPriority.LOW,
                    "medium": ZohoTicketPriority.MEDIUM,
                    "high": ZohoTicketPriority.HIGH,
                    "urgent": ZohoTicketPriority.URGENT
                }
                ticket_priority = priority_map.get(priority.lower(), ZohoTicketPriority.MEDIUM)

                # Handle different types of issues
                if issue_type in ["certificate_not_received", "certificate_incorrect_name", "certificate_qr_missing"]:
                    # Certificate-specific ticket creation
                    zoho_issue_type = issue_type.replace("certificate_", "")
                    response = await zoho_desk.create_certificate_issue_ticket(
                        user_name=user_name,
                        user_email=user_email,
                        user_mobile=user_mobile,
                        course_name=course_name,
                        issue_type=zoho_issue_type
                    )

                elif issue_type == "karma_points":
                    # Karma points issue ticket
                    subject = f"[IGOT KARMAYOGI ASSISTANT] Karma Points Issue - {user_name}"
                    description = f"""Karma Points Issue Request

User Details:
- Name: {user_name}
- Email: {user_email}
- Mobile: {user_mobile}

Issue Details:
- Issue Type: Karma Points Not Credited
- Course: {course_name if course_name else 'Not specified'}
- Description: {issue_description}

This ticket was created through the Karmayogi Bharat AI Assistant."""

                    ticket_data = ZohoTicketData(
                        subject=subject,
                        description=description,
                        user_name=user_name,
                        user_email=user_email,
                        user_mobile=user_mobile,
                        priority=ticket_priority,
                        category=ZohoIssueCategory.TECHNICAL_SUPPORT,
                        issue_type="Karma Points Issue",
                        course_name=course_name
                    )
                    response = await zoho_desk.create_ticket(ticket_data)

                elif issue_type == "profile_issue":
                    # Profile-related issue
                    response = await zoho_desk.create_profile_issue_ticket(
                        user_name=user_name,
                        user_email=user_email,
                        user_mobile=user_mobile,
                        issue_description=issue_description,
                        issue_type="profile_update"
                    )

                elif issue_type == "technical_support":
                    # Technical support issue
                    response = await zoho_desk.create_technical_support_ticket(
                        user_name=user_name,
                        user_email=user_email,
                        user_mobile=user_mobile,
                        issue_description=issue_description,
                        platform_section=course_name if course_name else ""
                    )

                else:
                    # General support ticket
                    subject = f"[IGOT KARMAYOGI ASSISTANT] General Support Request - {user_name}"
                    description = f"""General Support Request

User Details:
- Name: {user_name}
- Email: {user_email}
- Mobile: {user_mobile}

Issue Details:
- Description: {issue_description}
- Related Course/Event: {course_name if course_name else 'Not specified'}

This ticket was created through the Karmayogi Bharat AI Assistant."""

                    ticket_data = ZohoTicketData(
                        subject=subject,
                        description=description,
                        user_name=user_name,
                        user_email=user_email,
                        user_mobile=user_mobile,
                        priority=ticket_priority,
                        category=ZohoIssueCategory.GENERAL_INQUIRY,
                        issue_type="General Support",
                        course_name=course_name
                    )
                    response = await zoho_desk.create_ticket(ticket_data)

                if response.success:
                    return {
                        "success": True,
                        "ticket_id": response.ticket_id,
                        "ticket_number": response.ticket_number,
                        "message": f"Support ticket created successfully! Ticket ID: {response.ticket_number}",
                        "issue_type": issue_type,
                        "priority": priority
                    }
                else:
                    return {
                        "success": False,
                        "error": response.error_message,
                        "message": "Failed to create support ticket. Please try again or contact support directly."
                    }

            except Exception as e:
                logger.error(f"Error creating support ticket: {e}")
                return {
                    "success": False,
                    "error": str(e),
                    "message": "An error occurred while creating the support ticket. Please try again later."
                }

        # Run async function
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If we're in an async context, we need to handle this differently
                # Create a new event loop in a thread
                import concurrent.futures
                import threading

                def run_in_thread():
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    try:
                        return new_loop.run_until_complete(create_ticket())
                    finally:
                        new_loop.close()

                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(run_in_thread)
                    result = future.result(timeout=60)
            else:
                result = loop.run_until_complete(create_ticket())
        except Exception as e:
            logger.error(f"Error running ticket creation: {e}")
            result = {
                "success": False,
                "error": str(e),
                "message": "Failed to create support ticket due to system error."
            }

        return json.dumps(result, indent=2)

    # Build conversation context for the agent
    conversation_context = ""
    if current_chat_history:
        conversation_context = "\n\nRECENT CONVERSATION CONTEXT:\n"
        recent_messages = current_chat_history[-4:] if len(current_chat_history) >= 4 else current_chat_history

        for i, msg in enumerate(recent_messages):
            role = "User" if msg.role == "user" else "Assistant"
            conversation_context += f"{role}: {msg.content[:200]}...\n"


    # Build user context information
    user_info = f"""
USER CONTEXT:
- Name: {user_name}
- Email: {user_email}
- Mobile: {user_mobile}
- Course Enrollments: {len(user_context.get('course_enrollments', []))}
- Event Enrollments: {len(user_context.get('event_enrollments', []))}
"""

    agent_instruction = f"""You are a specialized support ticket creation assistant for the Karmayogi Bharat platform.

{user_info}

CORE RESPONSIBILITIES:
1. **Identify ticket-worthy issues** that require human support intervention
2. **Gather necessary information** to create comprehensive support tickets
3. **Create tickets in Zoho Desk** with proper categorization and details
4. **Provide ticket confirmation** and next steps to users

SUPPORTED TICKET TYPES:
1. **Certificate Issues**:
   - Certificate not received after course completion
   - Incorrect name on certificate
   - Missing QR code on certificate
   - Certificate format/download problems

2. **Karma Points Issues**:
   - Karma points not credited after course completion
   - Incorrect karma point calculations
   - Missing karma points for events
   - Note: Karma points are calculated based on learning hours spent per week with minimum criteria

3. **Profile/Account Issues**:
   - Unable to update profile information
   - Account access problems
   - Profile data discrepancies

4. **Technical Support**:
   - Platform functionality issues
   - Course access problems
   - System errors and bugs

5. **General Support**:
   - Any other support requests
   - Policy inquiries
   - General assistance

TICKET CREATION WORKFLOW:
1. **Issue Identification**: Determine the type of issue and whether it requires a support ticket
2. **Information Gathering**: Collect relevant details about the user's learning activities
3. **Ticket Creation**: Use the create_support_ticket function (always set priority to "low")
4. **Confirmation**: Provide ticket details and next steps to the user

INFORMATION TO GATHER FOR KARMA POINTS ISSUES:
- Clear description of the issue
- Which courses or events were completed recently
- When the courses/events were completed
- Any specific learning activities undertaken
- Time period when the issue was noticed

DO NOT ASK USERS:
- Expected number of karma points (users don't know the calculation formula)
- Priority level (always use "low" priority internally)
- Technical details about karma point calculations

RESPONSE GUIDELINES:
- Be empathetic and understanding of user frustrations
- Ask clarifying questions about learning activities and courses completed
- Do not mention ticket priority to users
- Set appropriate expectations for resolution timeline
- Provide ticket reference number for tracking
- Focus on gathering course/event completion information

EXAMPLE INTERACTIONS:
User: "I completed the course but didn't get my certificate"
Response: Gather details about course name, completion date, then create certificate_not_received ticket

User: "My karma points are not updated properly"
Response: Ask about recent courses/events completed, when they were finished, then create karma_points ticket with priority "low"

When creating tickets:
- Use the user's actual name, email, and mobile from the user context
- Always set priority to "low" (do not mention this to users)
- Provide clear, detailed descriptions
- Include relevant course/event information
- Give users clear next steps and expectations

{conversation_context}

Always use the create_support_ticket function when the user has a legitimate support issue that requires human intervention. Be thorough in gathering learning activity information but efficient in the process.
"""

    # FIXED: Use the function directly in tools list instead of types.Tool
    return Agent(
        name="ticket_creation_sub_agent",
        model="gemini-2.0-flash-001",
        description="Specialized agent for creating support tickets in Zoho Desk for Karmayogi platform issues",
        instruction=agent_instruction,
        tools=[create_support_ticket],  # FIXED: Pass function directly
        before_agent_callback=opik_tracer.before_agent_callback,
        after_agent_callback=opik_tracer.after_agent_callback,
        before_model_callback=opik_tracer.before_model_callback,
        after_model_callback=opik_tracer.after_model_callback,
    )