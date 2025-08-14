# agents/ticket_management_sub_agent.py
import logging
from typing import Dict, Any
from google.adk.agents import Agent
from opik import track

from utils.common_utils import call_gemini_api
from utils.request_context import RequestContext
from utils.zoho_utils import zoho_desk, ZohoTicketData, ZohoTicketPriority, ZohoIssueCategory

logger = logging.getLogger(__name__)


@track(name="ticket_creation_tool")
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

@track(name="ticket_status_tool")
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
            threads_text = """You are a support assistant for the Karmayogi Bharat platform. Your task is to summarize the ticket threads provided below. Focus on extracting key updates, issues raised, and any resolutions mentioned. Provide a concise summary that captures the essence of the conversation in a user-friendly format.

Please structure your response as:
1. Current Status: [Current state of the ticket]
2. Issue Summary: [Brief description of the original issue]
3. Recent Updates: [Any recent communications or progress]
4. Next Steps: [What to expect next, if mentioned]

Keep the summary concise but informative.
"""
            threads_text += "\n\nTicket Threads:\n" + "\n\n".join(
                [f"Thread {i + 1}:\n{thread.get('summary', thread.get('content', ''))}" for i, thread in
                 enumerate(threads_data.get("data", []))])

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

    agent_instruction = f"""You are a specialized support ticket management assistant for the Karmayogi Bharat platform.

{user_info}

CORE RESPONSIBILITIES:
1. **Create support tickets** for issues requiring human intervention
2. **Check ticket status** and provide updates to users
3. **Gather necessary information** for comprehensive ticket management
4. **Provide guidance** on next steps and expectations

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

TICKET STATUS QUERIES:
When users ask about ticket status:
1. **If ticket number is provided**: Use ticket_status_tool immediately
2. **If no ticket number**: Ask user to provide their ticket number
3. **Help users find ticket number**: Guide them to check their email confirmation
4. **Provide comprehensive status**: Include current status, updates, and next steps

COMMON STATUS QUERY PATTERNS TO RECOGNIZE:
- "Check my ticket status"
- "What's the status of my ticket?"
- "Any update on my support request?"
- "Check ticket [number]"
- "Status of ticket #[number]"
- "My ticket number is [number], what's the update?"

TICKET CREATION WORKFLOW:
1. **Issue Identification**: Determine the type of issue and whether it requires a support ticket
2. **Information Gathering**: Collect relevant details about the user's learning activities
3. **Ticket Creation**: Use the ticket_creation_tool to create the support ticket
4. **Confirmation**: Provide ticket details and next steps to the user

TICKET STATUS WORKFLOW:
1. **Number Validation**: Check if user provided a ticket number
2. **Request Number**: If not provided, ask user to share their ticket number
3. **Status Check**: Use ticket_status_tool with the provided number
4. **Provide Update**: Share comprehensive status information and next steps

INFORMATION TO GATHER FOR KARMA POINTS ISSUES:
- Clear description of the issue
- Which courses or events were completed recently
- When the courses/events were completed
- Any specific learning activities undertaken
- Time period when the issue was noticed

INFORMATION NEEDED FOR TICKET STATUS:
- Ticket number (absolutely required)
- Guide users to check email if they don't have the number

DO NOT ASK USERS:
- Expected number of karma points (users don't know the calculation formula)
- Priority level (always use "low" priority internally)
- Technical details about karma point calculations

RESPONSE GUIDELINES:
- Be empathetic and understanding of user frustrations
- Ask clarifying questions about learning activities and courses completed
- For status queries, always ask for ticket number if not provided
- Do not mention ticket priority to users
- Set appropriate expectations for resolution timeline
- Provide ticket reference number for tracking
- Focus on gathering course/event completion information for new tickets

EXAMPLE INTERACTIONS:

**Ticket Creation:**
User: "I completed the course but didn't get my certificate"
Response: Gather details about course name, completion date, then create certificate_not_received ticket

User: "My karma points are not updated properly"
Response: Ask about recent courses/events completed, when they were finished, then create karma_points ticket

**Ticket Status:**
User: "Check my ticket status"
Response: "I'd be happy to check your ticket status! Please provide your ticket number so I can look it up for you. You can find this in the email confirmation you received when the ticket was created."

User: "What's the status of ticket #12345?"
Response: Use ticket_status_tool immediately with "12345"

User: "Any update on my support request?"
Response: "I can check the status of your support request. Could you please share your ticket number? It should be in the email you received when you first reported the issue."

When creating tickets:
- Use the user's actual name, email, and mobile from the user context
- Always set priority to "low" (do not mention this to users)
- Provide clear, detailed descriptions
- Include relevant course/event information
- Give users clear next steps and expectations

When checking ticket status:
- Always require ticket number before proceeding
- Provide comprehensive updates including current status and next steps
- If ticket not found, guide user to verify the number
- Offer to help create a new ticket if the old one cannot be located

{conversation_context}

Always use the appropriate tool:
- ticket_creation_tool for new support issues
- ticket_status_tool for checking existing ticket status (requires ticket number)

Be thorough in gathering information but efficient in the process. Always ask for ticket numbers when users want status updates.
"""

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