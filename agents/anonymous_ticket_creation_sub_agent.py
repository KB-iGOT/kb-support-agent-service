# agents/anonymous_ticket_creation_sub_agent.py - Fixed version with proper tool structure
import json
import logging
import re
import asyncio
import concurrent.futures
import threading
from typing import List, Dict, Any
from google.adk.agents import Agent
from opik import track

from utils.zoho_utils import zoho_desk, ZohoTicketData, ZohoTicketPriority, ZohoIssueCategory
from utils.redis_session_service import ChatMessage

logger = logging.getLogger(__name__)


def validate_email(email: str) -> bool:
    """Validate email format"""
    if not email or not email.strip():
        return False

    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(email_pattern, email.strip()) is not None


def validate_mobile(mobile: str) -> bool:
    """Validate mobile number format (Indian format)"""
    if not mobile or not mobile.strip():
        return False

    # Remove spaces, dashes, parentheses
    clean_mobile = re.sub(r'[\s\-\(\)]', '', mobile.strip())

    # Check if it's 10 digits starting with 6-9 (Indian mobile format)
    if re.match(r'^[6-9]\d{9}$', clean_mobile):
        return True

    # Check if it's 10+ digits (international format)
    if re.match(r'^\d{10,15}$', clean_mobile):
        return True

    return False


@track(name="create_anonymous_support_ticket")
async def create_anonymous_support_ticket(issue_type: str, issue_description: str,
                                          user_name: str = "", user_email: str = "",
                                          user_mobile: str = "", priority: str = "low") -> dict:
    """
    Create a support ticket for anonymous users - REQUIRES valid contact information

    Args:
        issue_type: Type of issue (registration_issue, access_problem, technical_support, general_inquiry)
        issue_description: Detailed description of the issue
        user_name: User's name (REQUIRED)
        user_email: User's email (REQUIRED and must be valid)
        user_mobile: User's mobile (REQUIRED and must be valid)
        priority: Priority level (low, medium, high, urgent)

    Returns:
        Dict with ticket creation result or validation errors
    """
    try:
        logger.info(f"Attempting to create support ticket for anonymous user: {user_name or 'Unknown'}")

        # STRICT VALIDATION - REQUIRE ALL CONTACT INFORMATION
        validation_errors = []

        # Validate name
        if not user_name or not user_name.strip():
            validation_errors.append("Name is required to create a support ticket")

        # Validate email
        if not user_email or not user_email.strip():
            validation_errors.append("Email address is required to create a support ticket")
        elif not validate_email(user_email):
            validation_errors.append("Please provide a valid email address (e.g., user@example.com)")

        # Validate mobile (make it optional but if provided, must be valid)
        if user_mobile and user_mobile.strip() and not validate_mobile(user_mobile):
            validation_errors.append("Please provide a valid mobile number (10 digits)")

        # Validate issue description
        if not issue_description or not issue_description.strip() or len(issue_description.strip()) < 10:
            validation_errors.append(
                "Please provide a detailed description of your issue (at least 10 characters)")

        # Return validation errors if any
        if validation_errors:
            return {
                "success": False,
                "validation_errors": validation_errors,
                "message": "Please provide the required information to create your support ticket:",
                "required_fields": {
                    "name": "Your full name",
                    "email": "Valid email address for updates",
                    "mobile": "Mobile number (optional but recommended)",
                    "description": "Detailed description of your issue"
                }
            }

        # Clean and prepare contact information
        clean_name = user_name.strip()
        clean_email = user_email.strip().lower()
        clean_mobile = user_mobile.strip() if user_mobile else "Not provided"

        # Map priority string to enum
        priority_map = {
            "low": ZohoTicketPriority.LOW,
            "medium": ZohoTicketPriority.MEDIUM,
            "high": ZohoTicketPriority.HIGH,
            "urgent": ZohoTicketPriority.URGENT
        }
        ticket_priority = priority_map.get(priority.lower(), ZohoTicketPriority.MEDIUM)

        logger.info(f"Creating ticket for: {clean_name} ({clean_email}), Issue: {issue_type}")

        # Handle different types of anonymous user issues
        if issue_type == "registration_issue":
            subject = f"[IGOT KARMAYOGI ASSISTANT] Registration Issue - {clean_name}"
            description = f"""Registration Issue Request (Anonymous User)

User Details:
- Name: {clean_name}
- Email: {clean_email}
- Mobile: {clean_mobile}

Issue Details:
- Issue Type: Registration/Account Creation Issue
- Description: {issue_description}

Note: This ticket was created by an anonymous user through the Karmayogi Bharat AI Assistant.
User requires assistance with account creation or registration process.

Please contact the user at {clean_email} to resolve this issue."""

            ticket_data = ZohoTicketData(
                subject=subject,
                description=description,
                user_name=clean_name,
                user_email=clean_email,
                user_mobile=clean_mobile,
                priority=ticket_priority,
                category=ZohoIssueCategory.GENERAL_INQUIRY,
                issue_type="Registration Issue",
                course_name=""
            )

        elif issue_type == "access_problem":
            subject = f"[IGOT KARMAYOGI ASSISTANT] Platform Access Issue - {clean_name}"
            description = f"""Platform Access Issue (Anonymous User)

User Details:
- Name: {clean_name}
- Email: {clean_email}
- Mobile: {clean_mobile}

Issue Details:
- Issue Type: Platform Access Problem
- Description: {issue_description}

Note: This ticket was created by an anonymous user through the Karmayogi Bharat AI Assistant.
User is experiencing difficulties accessing the platform or specific features.

Please contact the user at {clean_email} to resolve this issue."""

            ticket_data = ZohoTicketData(
                subject=subject,
                description=description,
                user_name=clean_name,
                user_email=clean_email,
                user_mobile=clean_mobile,
                priority=ticket_priority,
                category=ZohoIssueCategory.TECHNICAL_SUPPORT,
                issue_type="Access Problem",
                course_name=""
            )

        elif issue_type == "technical_support":
            subject = f"[IGOT KARMAYOGI ASSISTANT] Technical Support - {clean_name}"
            description = f"""Technical Support Request (Anonymous User)

User Details:
- Name: {clean_name}
- Email: {clean_email}
- Mobile: {clean_mobile}

Issue Details:
- Issue Type: Technical Support
- Description: {issue_description}

Note: This ticket was created by an anonymous user through the Karmayogi Bharat AI Assistant.
Technical assistance required for platform functionality.

Please contact the user at {clean_email} to resolve this issue."""

            ticket_data = ZohoTicketData(
                subject=subject,
                description=description,
                user_name=clean_name,
                user_email=clean_email,
                user_mobile=clean_mobile,
                priority=ticket_priority,
                category=ZohoIssueCategory.TECHNICAL_SUPPORT,
                issue_type="Technical Support",
                course_name=""
            )

        else:  # general_inquiry
            subject = f"[IGOT KARMAYOGI ASSISTANT] General Inquiry - {clean_name}"
            description = f"""General Inquiry (Anonymous User)

User Details:
- Name: {clean_name}
- Email: {clean_email}
- Mobile: {clean_mobile}

Issue Details:
- Issue Type: General Inquiry
- Description: {issue_description}

Note: This ticket was created by an anonymous user through the Karmayogi Bharat AI Assistant.
General assistance or information requested.

Please contact the user at {clean_email} to resolve this issue."""

            ticket_data = ZohoTicketData(
                subject=subject,
                description=description,
                user_name=clean_name,
                user_email=clean_email,
                user_mobile=clean_mobile,
                priority=ticket_priority,
                category=ZohoIssueCategory.GENERAL_INQUIRY,
                issue_type="General Inquiry",
                course_name=""
            )

        # Create the ticket in Zoho
        response = await zoho_desk.create_ticket(ticket_data)

        if response.success:
            return {
                "success": True,
                "ticket_id": response.ticket_id,
                "ticket_number": response.ticket_number,
                "message": f"✅ Support ticket created successfully!\n\n📋 Ticket Number: {response.ticket_number}\n📧 Updates will be sent to: {clean_email}\n\n⏱️ Expected Response: Within 24-48 hours\n\nThank you for contacting Karmayogi Bharat support!",
                "issue_type": issue_type,
                "priority": priority,
                "user_type": "anonymous",
                "contact_email": clean_email
            }
        else:
            return {
                "success": False,
                "error": response.error_message,
                "message": "❌ Failed to create support ticket. Please try again or contact support directly at support@karmayogibharat.gov.in"
            }

    except Exception as e:
        logger.error(f"Error creating anonymous support ticket: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": "❌ An error occurred while creating the support ticket. Please try again later or contact support directly."
        }


# Wrapper function for tool compatibility
def create_anonymous_support_ticket_tool(issue_type: str, issue_description: str,
                                         user_name: str = "", user_email: str = "",
                                         user_mobile: str = "", priority: str = "low") -> str:
    """
    Synchronous wrapper for the async ticket creation function
    Returns JSON string for compatibility with Agent tools
    """
    def run_async_ticket_creation():
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If we're in an async context, we need to handle this differently
                # Create a new event loop in a thread
                def run_in_thread():
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    try:
                        return new_loop.run_until_complete(
                            create_anonymous_support_ticket(
                                issue_type, issue_description, user_name,
                                user_email, user_mobile, priority
                            )
                        )
                    finally:
                        new_loop.close()

                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(run_in_thread)
                    result = future.result(timeout=60)
            else:
                result = loop.run_until_complete(
                    create_anonymous_support_ticket(
                        issue_type, issue_description, user_name,
                        user_email, user_mobile, priority
                    )
                )
        except Exception as e:
            logger.error(f"Error running ticket creation: {e}")
            result = {
                "success": False,
                "error": str(e),
                "message": "Failed to create support ticket due to system error."
            }

        return result

    # Execute the async function
    result = run_async_ticket_creation()
    return json.dumps(result, indent=2)


def create_anonymous_ticket_creation_sub_agent(opik_tracer, current_chat_history: List[ChatMessage],
                                               user_context: Dict[str, Any]) -> Agent:
    """
    Create a specialized sub-agent for handling support ticket creation for anonymous/guest users
    REQUIRES contact information collection before ticket creation
    """

    # Build conversation context for the agent
    conversation_context = ""
    if current_chat_history:
        conversation_context = "\n\nRECENT CONVERSATION CONTEXT:\n"
        recent_messages = current_chat_history[-4:] if len(current_chat_history) >= 4 else current_chat_history

        for i, msg in enumerate(recent_messages):
            role = "User" if msg.role == "user" else "Assistant"
            conversation_context += f"{role}: {msg.content[:200]}...\n"

    agent_instruction = f"""You are a specialized support ticket creation assistant for anonymous/guest users of the Karmayogi Bharat platform.

USER STATUS: Anonymous/Guest User (Not Logged In)

🎯 PRIMARY GOAL: Help anonymous users create support tickets by collecting REQUIRED contact information

📋 MANDATORY INFORMATION TO COLLECT BEFORE TICKET CREATION:
1. **Full Name** (required) - User's complete name for ticket identification
2. **Email Address** (required) - Valid email for ticket updates and communication
3. **Mobile Number** (recommended) - For urgent communication (optional but encouraged)
4. **Issue Description** (required) - Clear, detailed description of the problem

⚠️ CRITICAL: DO NOT create tickets without name and valid email address!

🎫 SUPPORTED TICKET TYPES FOR ANONYMOUS USERS:
1. **registration_issue**: Account creation problems, email verification issues
2. **access_problem**: Cannot access platform, login difficulties, browser issues
3. **technical_support**: Website functionality, performance problems, errors
4. **general_inquiry**: Platform information, policy questions, general assistance

📝 INFORMATION GATHERING WORKFLOW:
1. **Issue Identification**: Understand the specific problem type
2. **Contact Information Collection**: 
   - Ask for full name
   - Request email address (validate format)
   - Ask for mobile number (optional)
3. **Issue Details**: Get comprehensive description of the problem
4. **Validation**: Ensure all required fields are provided
5. **Ticket Creation**: Use create_anonymous_support_ticket_tool function
6. **Confirmation**: Provide ticket number and next steps

💬 CONVERSATION GUIDELINES:

**Initial Contact Information Request:**
"To create a support ticket and ensure we can assist you properly, I'll need some contact information:

1. What's your full name?
2. What's your email address? (We'll send updates here)
3. Could you provide your mobile number? (Optional, but helpful for urgent issues)
4. Please describe your issue in detail."

**Email Validation:**
- Check email format (user@domain.com)
- If invalid: "Please provide a valid email address like: yourname@example.com"

**Mobile Validation:**
- Accept Indian format (10 digits starting with 6-9)
- Accept international format (10-15 digits)
- If invalid: "Please provide a valid mobile number (10 digits)"

**Missing Information Handling:**
- If name missing: "I need your full name to create the ticket"
- If email missing: "A valid email address is required for ticket updates"
- If description too short: "Please provide more details about your issue"

**Successful Ticket Creation:**
- Confirm ticket number
- Mention email for updates
- Provide expected response time
- Offer additional assistance

🚫 DO NOT:
- Create tickets with placeholder contact information
- Accept obviously fake emails (test@test.com, etc.)
- Skip validation steps
- Mention ticket priority to users (always use "low" internally)

✅ DO:
- Be patient and helpful during information collection
- Validate email format before proceeding
- Explain why contact information is needed
- Provide clear next steps after ticket creation
- Set appropriate expectations for response time

📧 AFTER TICKET CREATION:
- Provide ticket reference number
- Confirm the email where updates will be sent
- Explain they'll receive confirmation email
- Mention expected response timeframe (24-48 hours)
- Ask if they need any other assistance

{conversation_context}

Remember: Valid contact information is MANDATORY for ticket creation. Be helpful but firm about collecting required details.
"""

    return Agent(
        name="anonymous_ticket_creation_sub_agent",
        model="gemini-2.0-flash-001",
        description="Specialized agent for creating support tickets for anonymous users with mandatory contact info collection",
        instruction=agent_instruction,
        tools=[create_anonymous_support_ticket_tool],
        before_agent_callback=opik_tracer.before_agent_callback,
        after_agent_callback=opik_tracer.after_agent_callback,
        before_model_callback=opik_tracer.before_model_callback,
        after_model_callback=opik_tracer.after_model_callback,
    )