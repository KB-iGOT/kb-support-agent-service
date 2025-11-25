# agents/ticket_management_sub_agent.py
import logging
import os
from typing import Dict, Any
from google.adk.agents import Agent
from opik import track

from utils.common_utils import call_gemini_api
from utils.request_context import RequestContext
from utils.zoho_utils import zoho_desk, ZohoTicketData, ZohoTicketPriority, ZohoIssueCategory
from utils.prompt_loader import get_prompt

logger = logging.getLogger(__name__)

# Get Opik project name from environment
OPIK_PROJECT = os.getenv("OPIK_PROJECT", "default")


@track(name="ticket_creation_tool", project_name=OPIK_PROJECT)
async def ticket_creation_tool(user_message: str, request_context: RequestContext = None) -> dict:
    """
    Create support tickets in Zoho Desk with context (THREAD-SAFE)
    """
    try:
        logger.info("Creating support ticket with request context")

        if not request_context or not request_context.user_context:
            return {"success": False, "error": "User context not available"}

        # ✅ FIXED: Use context instead of global variables
        user_context = request_context.user_context
        chat_history = request_context.chat_history or []

        profile_data = user_context.get('profile', {})
        user_name = profile_data.get('firstName', 'User')
        user_email = profile_data.get('profileDetails', {}).get('personalDetails', {}).get('primaryEmail', '')
        user_mobile = profile_data.get('profileDetails', {}).get('personalDetails', {}).get('mobile', '')

        logger.info(f"Creating support ticket for user: {user_name}")

        # Analyze the user message to extract ticket information
        ticket_info = await _analyze_ticket_request(user_message)

        if not ticket_info:
            return {
                "success": False,
                "error": "Could not analyze ticket request"
            }

        # Create the ticket
        response = await _create_zoho_ticket(
            ticket_info=ticket_info,
            user_name=user_name,
            user_email=user_email,
            user_mobile=user_mobile,
            user_context=user_context
        )

        if response.get("success"):
            return {
                "success": True,
                "response": f"🎫 **Support Ticket Created Successfully!**\n\n**Ticket ID:** {response.get('ticket_number')}\n\n**Issue Type:** {ticket_info.get('issue_type', 'General Support')}\n\n**Next Steps:**\n• Our support team will review your request\n• You'll receive updates via email\n• Response time: 24-48 hours\n\n**Reference:** Keep this ticket ID for future correspondence: **{response.get('ticket_number')}**",
                "ticket_id": response.get("ticket_id"),
                "ticket_number": response.get("ticket_number"),
                "data_type": "support_ticket"
            }
        else:
            return {
                "success": False,
                "error": response.get("error", "Failed to create ticket"),
                "response": "❌ **Ticket Creation Failed**\n\nI apologize, but I couldn't create your support ticket right now.\n\n**Please try:**\n• Contact support directly\n• Try again in a few minutes\n• Email support team\n\nYour issue is important to us!"
            }

    except Exception as e:
        logger.error(f"Error in ticket_creation_tool: {e}")
        return {
            "success": False,
            "error": str(e),
            "response": "❌ **Technical Error**\n\nI encountered an error while creating your support ticket. Please contact support directly or try again later."
        }

@track(name="ticket_status_tool", project_name=OPIK_PROJECT)
async def ticket_status_tool(ticket_number: str, request_context: RequestContext = None) -> dict:
    """
    Check the status of a support ticket in Zoho Desk (THREAD-SAFE)
    """
    global ticket_id, ticket_status, ticket_subject
    try:
        if not request_context or not request_context.user_context:
            return {"success": False, "error": "User context not available"}

        # ✅ FIXED: Use context instead of global variables
        user_context = request_context.user_context
        profile_data = user_context.get('profile', {})
        user_name = profile_data.get('firstName', 'User')
        user_email = profile_data.get('profileDetails', {}).get('personalDetails', {}).get('primaryEmail', '')

        logger.info(f"Checking ticket status for user: {user_name}, Ticket Number: {ticket_number}")

        # Validate ticket number format
        if not ticket_number or not ticket_number.strip():
            return {
                "success": False,
                "error": "Invalid ticket number",
                "response": "❌ **Invalid Ticket Number**\n\nPlease provide a valid ticket number to check the status."
            }

        # Clean the ticket number (remove any extra spaces or characters)
        ticket_number = ticket_number.strip()

        # Fetch ticket status from Zoho Desk
        search_success, search_data = await zoho_desk.search_ticket_by_number(ticket_number)
        logger.debug(f"Search response for ticket number {ticket_number}: {search_success}, {search_data}")

        if search_success and "data" in search_data and search_data.get("data") and len(search_data["data"]) > 0:

            if search_data["data"][0]["email"] != user_email:
                # If the ticket does not belong to the user, return an error
                return {
                    "success": False,
                    "error": "Ticket does not belong to this user",
                    "response": "❌ **Ticket Not Found**\n\nThis ticket does not belong to your account. Please check the ticket number or contact support for assistance."
                }

            ticket_id = search_data["data"][0]["id"]
            ticket_status = search_data["data"][0].get("status", "Unknown")
            ticket_subject = search_data["data"][0].get("subject", "No subject")
        else:
            # Handle case where no tickets are found
            ticket_id = None

        logger.info(f"Fetched Id for Ticket Number: {ticket_number}, Ticket Id: {ticket_id}")

        if not ticket_id:
            return {
                "success": False,
                "error": "Ticket not found",
                "response": f"❌ **Ticket Not Found**\n\nI couldn't find any ticket with the number **{ticket_number}**.\n\n**Please check:**\n• The ticket number is correct\n• The ticket belongs to your account\n• Try again with the full ticket number\n\nIf you need help finding your ticket number, check your email for the ticket confirmation."
            }

        # Get ticket threads for detailed information
        threads_success, threads_data = await zoho_desk.get_ticket_threads(ticket_id)
        logger.debug(f"Fetched threads for Ticket ID {ticket_id}: {threads_data}")
        # Summarize ticket threads using Gemini
        if threads_success and "data" in threads_data and threads_data["data"]:
            # add prompt to gemini to summarize the ticket threads
            formatted_threads = "\n\n".join(
                [
                    f"Thread {i + 1}:\n{thread.get('summary', thread.get('content', ''))}"
                    for i, thread in enumerate(threads_data.get("data", []))
                ]
            )

            threads_text = get_prompt(
                "ticket_management",
                "threads_summary_prompt",
                ticket_threads=formatted_threads,
            )

            logger.debug(f"Threads text for summarization: {threads_text}")

            # Call Gemini for summarization
            summary = await call_gemini_api(threads_text)

            logger.debug(f"LLM summarised response: {summary}")

            return {
                "success": True,
                "ticket_number": ticket_number,
                "ticket_status": ticket_status,
                "ticket_subject": ticket_subject,
                "summary": summary,
                "response": f"📋 **Ticket Status for #{ticket_number}**\n\n**Subject:** {ticket_subject}\n**Current Status:** {ticket_status}\n\n**Summary:**\n{summary}\n"
            }
        else:
            # If no threads found, still provide basic ticket info
            return {
                "success": True,
                "ticket_number": ticket_number,
                "ticket_status": ticket_status,
                "ticket_subject": ticket_subject,
                "response": f"📋 **Ticket Status for #{ticket_number}**\n\n**Subject:** {ticket_subject}\n**Current Status:** {ticket_status}\n\n**Note:** No detailed updates are available yet. Our support team will update you as soon as there's progress on your ticket.\n"
            }

    except Exception as e:
        logger.error(f"Error in ticket_status_tool: {e}")
        return {
            "success": False,
            "error": str(e),
            "response": "❌ **Technical Error**\n\nI encountered an error while checking your ticket status. Please try again later or contact support directly."
        }

async def _analyze_ticket_request(user_message: str) -> Dict[str, Any]:
    """Fallback rule-based ticket analysis (THREAD-SAFE)"""
    message_lower = user_message.lower()

    # Certificate issues
    if any(word in message_lower for word in ["certificate", "cert"]):
        if any(word in message_lower for word in ["didn't get", "not received", "haven't received"]):
            issue_type = "certificate_not_received"
        elif any(word in message_lower for word in ["wrong name", "incorrect name", "misspelled"]):
            issue_type = "certificate_incorrect_name"
        elif any(word in message_lower for word in ["qr code", "qr", "missing qr"]):
            issue_type = "certificate_qr_missing"
        else:
            issue_type = "certificate_not_received"

    # Karma points issues
    elif any(word in message_lower for word in ["karma points", "karma", "points not credited"]):
        issue_type = "karma_points"

    # Profile issues
    elif any(word in message_lower for word in ["profile", "update", "change my"]):
        issue_type = "profile_issue"

    # Technical issues
    elif any(word in message_lower for word in ["not working", "error", "bug", "broken", "can't access"]):
        issue_type = "technical_support"

    else:
        issue_type = "general"

    return {
        "issue_type": issue_type,
        "issue_description": user_message,
        "course_name": "",
        "priority": "low",
        "requires_ticket": True
    }


async def _create_zoho_ticket(ticket_info: Dict[str, Any], user_name: str, user_email: str,
                              user_mobile: str, user_context: Dict[str, Any]) -> Dict[str, Any]:
    """Create ticket in Zoho Desk (THREAD-SAFE)"""
    try:
        issue_type = ticket_info.get("issue_type", "general")
        issue_description = ticket_info.get("issue_description", "")
        course_name = ticket_info.get("course_name", "")
        priority = ticket_info.get("priority", "low")

        # Map priority string to enum
        priority_map = {
            "low": ZohoTicketPriority.LOW,
            "medium": ZohoTicketPriority.MEDIUM,
            "high": ZohoTicketPriority.HIGH,
            "urgent": ZohoTicketPriority.URGENT
        }
        ticket_priority = priority_map.get(priority.lower(), ZohoTicketPriority.LOW)

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
        logger.error(f"Error creating Zoho ticket: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": "An error occurred while creating the support ticket."
        }



def create_ticket_management_sub_agent(opik_tracer, request_context: RequestContext) -> Agent:
    """
    Create a specialized sub-agent for handling support ticket creation and status requests

    This agent handles:
    - Certificate issues (not received, incorrect name, QR code missing)
    - Karma points issues
    - Profile/account issues
    - Technical support requests
    - General support ticket creation
    - Ticket status queries
    """


    user_context = request_context.user_context
    current_chat_history = request_context.chat_history or []

    profile_data = user_context.get('profile', {})
    user_name = profile_data.get('firstName', 'User')
    user_email = profile_data.get('profileDetails', {}).get('personalDetails', {}).get('primaryEmail', '')
    user_mobile = profile_data.get('profileDetails', {}).get('personalDetails', {}).get('mobile', '')

    # Create tools that will receive context as parameter
    def make_tool_with_context(tool_func):
        """Wrapper to inject request context into tools"""

        async def wrapped_tool(user_message: str) -> dict:
            return await tool_func(user_message, request_context)

        wrapped_tool.__name__ = tool_func.__name__
        return wrapped_tool

    # Create specific wrapper for ticket_status_tool
    def make_status_tool_with_context():
        """Wrapper specifically for ticket status tool"""

        async def wrapped_status_tool(ticket_number: str) -> dict:
            return await ticket_status_tool(ticket_number, request_context)

        wrapped_status_tool.__name__ = "ticket_status_tool"
        return wrapped_status_tool

    tools = [
        make_tool_with_context(ticket_creation_tool),
        make_status_tool_with_context()
    ]

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

    agent_instruction = get_prompt(
          "ticket_management",
          "instruction",
          user_info=user_info,
          conversation_context=conversation_context,
     )

    return Agent(
        name="ticket_creation_sub_agent",
        model="gemini-2.0-flash-001",
        description="Specialized agent for creating and checking support tickets in Zoho Desk for Karmayogi platform issues (THREAD-SAFE)",
        instruction=agent_instruction,
        tools=tools,  # ✅ FIXED: Use wrapped tools with context
        before_agent_callback=opik_tracer.before_agent_callback,
        after_agent_callback=opik_tracer.after_agent_callback,
        before_model_callback=opik_tracer.before_model_callback,
        after_model_callback=opik_tracer.after_model_callback,
        before_tool_callback=opik_tracer.before_tool_callback,
        after_tool_callback=opik_tracer.after_tool_callback,
    )