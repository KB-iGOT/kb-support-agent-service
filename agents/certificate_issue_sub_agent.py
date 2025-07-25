# agents/certificate_issue_sub_agent.py
import json
import logging
import os
import jwt
import time
from typing import List, Optional

import httpx
from google.adk.agents import Agent
from opik import track

logger = logging.getLogger(__name__)

user_token = None

def is_token_expired(token):
    try:
        payload = jwt.decode(token, options={"verify_signature": False})
        exp = payload.get("exp")
        if exp and exp < int(time.time()):
            return True
        return False
    except Exception:
        return True  # Treat decode errors as expired


def get_user_token():
    """
    Generate a user token for authentication.
    This function should be called before any API requests that require authentication.
    """
    global user_token
    # if user_token is empty OR if user_token (jwt token) is expired, then generate new token
    if not user_token or is_token_expired(user_token):
        url = f"{os.getenv('portal_endpoint', '')}{os.getenv('access_token_api', '')}"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data = {
            "client_id": "admin-cli",
            "grant_type": "password",
            "username": os.getenv('system_admin_user', ''),
            "password": os.getenv('system_admin_password', '@8887')
        }
        try:
            response = httpx.post(url, headers=headers, data=data, timeout=30.0)
            if response.status_code == 200:
                token_data = response.json()
                user_token = token_data.get('access_token')
                logger.info("User token generated successfully")
            else:
                logger.error(f"Failed to generate user token: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"Error generating user token: {e}")
            raise e

    return user_token


@track(name="certificate_issue_handler")
async def certificate_issue_handler(user_message: str) -> dict:
    """
    Handle certificate-related issues including incorrect names, missing certificates, and QR code issues.

    Cases handled:
    1. Incorrect name on certificate
    2. Certificate not received after completion
    3. QR code missing on certificate
    """
    from main import user_context, current_chat_history, _rephrase_query_with_history

    try:
        logger.info("Processing certificate issue request")

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

        # Enhance query with rephrasing if needed
        print(f"Original User message for certificate issue: {user_message}")
        if len(user_message.split()) < 4:
            rephrased_query = await _rephrase_query_with_history(user_message, current_chat_history)
        else:
            rephrased_query = user_message
        print(f"Rephrased User message for certificate issue: {rephrased_query}")

        # Extract user information
        profile_data = user_context.get('profile', {})
        user_id = profile_data.get('identifier', '')
        user_name = profile_data.get('firstName', 'User')
        user_email = profile_data.get('profileDetails', {}).get('personalDetails', {}).get('primaryEmail', '')
        user_mobile = profile_data.get('profileDetails', {}).get('personalDetails', {}).get('mobile', '')

        # Analyze the certificate issue workflow state
        workflow_state = await _analyze_certificate_issue_workflow(rephrased_query, current_chat_history)

        logger.info(f"Certificate issue workflow state: {json.dumps(workflow_state)}")

        # Handle different workflow steps
        if workflow_state['step'] == 'course_identification':
            return await _handle_course_identification(workflow_state, user_context, history_context)

        elif workflow_state['step'] == 'course_verification':
            return await _handle_course_verification(workflow_state, user_id, user_name, user_email, user_mobile)

        elif workflow_state['step'] == 'certificate_reissue':
            return await _handle_certificate_reissue(workflow_state, user_id, user_name, user_email, user_mobile)

        elif workflow_state['step'] == 'support_ticket':
            return await _handle_support_ticket_creation(workflow_state, user_name, user_email, user_mobile)

        else:
            # Initial request - analyze issue type and guide user
            return await _handle_initial_certificate_request(workflow_state, user_message, rephrased_query,
                                                             user_context, history_context)

    except Exception as e:
        logger.error(f"Error in certificate_issue_handler: {e}")
        return {"success": False, "error": str(e)}


# Fix for _analyze_certificate_issue_workflow function in certificate_issue_sub_agent.py

async def _analyze_certificate_issue_workflow(query: str, chat_history: List) -> dict:
    """
    Enhanced certificate issue workflow analyzer with better course name and issue type detection.
    """
    from main import _call_local_llm

    # Prepare chat history context
    history_context = ""
    if chat_history:
        history_context = "\nRecent conversation history:\n"
        for msg in chat_history[-4:]:
            role = "User" if msg.role == "user" else "Assistant"
            history_context += f"{role}: {msg.content}\n"

    system_prompt = f"""
You are a certificate issue workflow analyzer for Karmayogi Bharat platform.

CERTIFICATE ISSUE TYPES:
1. "incorrect_name" - Name on certificate is wrong/misspelled
2. "not_received" - Certificate not received after course completion (DEFAULT for certificate requests)
3. "qr_missing" - QR code missing from certificate
4. "general_issue" - Other certificate-related problems

WORKFLOW STEPS:
1. "initial" - First time user reports certificate issue
2. "course_identification" - Need to identify which course has the certificate issue
3. "course_verification" - Verify user's enrollment and completion status for the course
4. "certificate_reissue" - Attempt to reissue certificate (for not_received/qr_missing cases)
5. "support_ticket" - Create support ticket for manual resolution (for incorrect_name cases)

COURSE NAME EXTRACTION RULES:
- Look for course names anywhere in the text
- Extract names after "course", "for course", "named", "called", etc.
- Course names can be in quotes or without quotes
- Extract full course titles, including partial names

ISSUE TYPE DETERMINATION:
- If user asks for certificate/wants certificate → "not_received"
- If user mentions wrong name → "incorrect_name"  
- If user mentions QR code → "qr_missing"
- Default to "not_received" for certificate requests

STEP DETERMINATION LOGIC:
- If course name is provided → "course_verification" (go straight to verification)
- If issue type identified but no course name → "course_identification"
- If user just mentions certificate problem → "initial"

EXAMPLES:
Query: "Give me certificate for course The Tribal Heritage Village"
→ step: "course_verification", issue_type: "not_received", course_name: "The Tribal Heritage Village"

Query: "Course name is En Uru - The Tribal Heritage Village of Wayanad"
→ step: "course_verification", issue_type: "not_received", course_name: "En Uru - The Tribal Heritage Village of Wayanad"

Query: "I want certificate for Python course"
→ step: "course_verification", issue_type: "not_received", course_name: "Python course"

Query: "My certificate has wrong name"
→ step: "course_identification", issue_type: "incorrect_name", course_name: ""

Query: "Certificate problem"
→ step: "initial", issue_type: "general_issue", course_name: ""

Given the query and history, output a JSON object with:
- step: (initial, course_identification, course_verification, certificate_reissue, support_ticket)
- issue_type: (incorrect_name, not_received, qr_missing, general_issue)
- course_name: (string, extracted course name if found)
- user_provided_course: (true if course name found, false otherwise)
- requires_course_name: (false if course name provided, true otherwise)

IMPORTANT: If a course name is mentioned anywhere, set step to "course_verification" and issue_type to "not_received" by default.

Query: {query}
{history_context}

Respond ONLY with the JSON object.
"""

    llm_response = await _call_local_llm(system_prompt, query)
    print(f"LLM response for certificate workflow analysis: {llm_response}")

    # Parse LLM response
    try:
        state = json.loads(llm_response)

        # Enhanced validation and defaults
        required_fields = ['step', 'issue_type', 'course_name', 'user_provided_course', 'requires_course_name']
        for field in required_fields:
            if field not in state:
                if field == 'course_name':
                    state[field] = ''
                else:
                    state[field] = False

        # Enhanced course name extraction if LLM missed it
        if not state.get('course_name'):
            course_name = _extract_course_name_fallback(query)
            if course_name:
                state['course_name'] = course_name
                state['user_provided_course'] = True
                state['requires_course_name'] = False
                state['step'] = 'course_verification'
                if not state.get('issue_type') or state['issue_type'] == '':
                    state['issue_type'] = 'not_received'

        # Fix empty issue_type
        if not state.get('issue_type') or state['issue_type'] == '':
            if 'wrong name' in query.lower() or 'incorrect name' in query.lower():
                state['issue_type'] = 'incorrect_name'
            elif 'qr code' in query.lower() or 'qr missing' in query.lower():
                state['issue_type'] = 'qr_missing'
            else:
                state['issue_type'] = 'not_received'  # Default for certificate requests

        # Fix step logic
        if state.get('course_name') and state['step'] in ['initial', 'course_identification', 'awaiting_course_name']:
            state['step'] = 'course_verification'

        print(f"Final workflow state: {json.dumps(state)}")

    except Exception as e:
        print(f"Error parsing LLM response: {e}")
        # Enhanced fallback logic
        course_name = _extract_course_name_fallback(query)
        if course_name:
            state = {
                'step': 'course_verification',
                'issue_type': 'not_received',
                'course_name': course_name,
                'user_provided_course': True,
                'requires_course_name': False
            }
        else:
            state = {
                'step': 'initial',
                'issue_type': 'general_issue',
                'course_name': '',
                'user_provided_course': False,
                'requires_course_name': True
            }

    return state


def _extract_course_name_fallback(query: str) -> str:
    """
    Fallback course name extraction using pattern matching.
    """
    import re

    query_lower = query.lower()

    # Pattern 1: "course name is [name]"
    match = re.search(r'course name is (.+?)(?:\.|$)', query_lower)
    if match:
        return match.group(1).strip()

    # Pattern 2: "for course [name]"
    match = re.search(r'for course (.+?)(?:\.|$)', query_lower)
    if match:
        return match.group(1).strip()

    # Pattern 3: "course [name]"
    match = re.search(r'course (.+?)(?:\.|$)', query_lower)
    if match:
        name = match.group(1).strip()
        # Filter out common words that aren't course names
        if name not in ['name', 'is', 'the', 'a', 'an']:
            return name

    # Pattern 4: Extract quoted names
    match = re.search(r'"([^"]+)"', query)
    if match:
        return match.group(1).strip()

    # Pattern 5: Extract names after common keywords
    patterns = [
        r'named (.+?)(?:\.|$)',
        r'called (.+?)(?:\.|$)',
        r'titled (.+?)(?:\.|$)',
    ]

    for pattern in patterns:
        match = re.search(pattern, query_lower)
        if match:
            return match.group(1).strip()

    return ''


# Enhanced course verification function to ensure PostgreSQL is used
async def _handle_course_verification(state: dict, user_id: str, user_name: str, user_email: str,
                                      user_mobile: str) -> dict:
    """
    Enhanced course verification with guaranteed PostgreSQL usage and certificate reissue.
    """
    course_name = state['course_name']
    issue_type = state['issue_type']

    try:
        logger.info(f"Starting course verification for: {course_name}")

        # FORCE PostgreSQL course lookup
        matching_course = await _find_matching_course_postgresql(user_id, course_name)
        print(f"_handle_course_verification :: matching_course: {matching_course}")

        if not matching_course:
            logger.warning(f"Course not found in PostgreSQL: {course_name}")
            return {
                "success": True,
                "response": f"I'm sorry! I am not able to find your enrollment details for the '{course_name}' course. Please check the course name and try again, or contact support if you believe this is an error.",
                "data_type": "certificate_issue",
                "step": "course_not_found",
                "issue_type": issue_type,
                "course_name": course_name
            }

        logger.info(f"Found course: {matching_course.get('course_name', 'Unknown')} || identifier:: {matching_course.get('course_identifier','')}")

        # Check completion status
        completion_status = matching_course.get('course_completion_status', '').lower()
        completion_percentage = float(matching_course.get('course_completion_percentage', 0))
        issued_certificate_id = matching_course.get('course_issued_certificate_id', '')

        logger.info(
            f"Course status: {completion_status}, Progress: {completion_percentage}%, Certificate: {bool(issued_certificate_id)}")

        # Course not completed
        if completion_status != 'completed' or completion_percentage < 100:
            return {
                "success": True,
                "response": f"I understand that you are yet to complete the '{course_name}' course. Please complete the course to receive the certificate. Your current progress is {completion_percentage}%.",
                "data_type": "certificate_issue",
                "step": "course_not_completed",
                "issue_type": issue_type,
                "course_name": course_name,
                "completion_percentage": completion_percentage
            }

        # Course completed - check if certificate already exists
        if issued_certificate_id and issue_type == "not_received":
            return {
                "success": True,
                "response": f"Great news! You already have a certificate for '{course_name}'. Your certificate ID is '{issued_certificate_id}'. If you're having trouble accessing it, please check your dashboard or contact support at mission.karmayogi@gov.in.",
                "data_type": "certificate_issue",
                "step": "certificate_exists",
                "issue_type": issue_type,
                "course_name": course_name,
                "certificate_id": issued_certificate_id
            }

        # Course completed but no certificate - proceed with reissue
        if not issued_certificate_id or issue_type in ["not_received", "qr_missing"]:
            logger.info(f"Proceeding with certificate reissue for completed course: {course_name}")
            return await _handle_certificate_reissue(state, user_id, user_name, user_email, user_mobile,
                                                     matching_course)

        # For incorrect name issues
        if issue_type == "incorrect_name":
            return await _handle_support_ticket_creation(state, user_name, user_email, user_mobile, matching_course)

        # Default case
        return await _handle_certificate_reissue(state, user_id, user_name, user_email, user_mobile, matching_course)

    except Exception as e:
        logger.error(f"Error in course verification: {e}")
        return {
            "success": True,
            "response": f"I encountered an error while verifying your enrollment for '{course_name}'. Please try again or contact support for assistance.",
            "data_type": "certificate_issue",
            "step": "verification_error",
            "issue_type": issue_type,
            "course_name": course_name
        }

async def _handle_course_identification(state: dict, user_context: dict, history_context: str) -> dict:
    """
    Handle course identification step - ask user to specify the course name.
    """
    from main import _call_local_llm

    # Get user's enrollment summary for context
    enrollment_summary = user_context.get('enrollment_summary', {})
    total_courses = enrollment_summary.get('total_courses_completed', 0)
    total_events = enrollment_summary.get('total_events_completed', 0)

    issue_type = state['issue_type']

    # Customize response based on issue type
    if issue_type == "incorrect_name":
        base_message = "I understand you're having an issue with an incorrect name on your certificate. "
    elif issue_type == "not_received":
        base_message = "I see you haven't received a certificate that you were expecting. "
    elif issue_type == "qr_missing":
        base_message = "I understand there's a QR code missing from your certificate. "
    else:
        base_message = "I understand you're having a certificate-related issue. "

    system_message = f"""
You are helping a user identify which course has a certificate issue.

User's completion summary:
- Completed courses: {total_courses}
- Completed events: {total_events}

Issue type: {issue_type}
Base message: {base_message}

{history_context}

Provide a helpful response that:
1. Acknowledges their certificate issue
2. Asks them to specify the course name
3. Provides guidance on how to identify the course
4. Is professional and supportive

Keep the response conversational and under 150 words.
"""

    response = await _call_local_llm(system_message, base_message)

    return {
        "success": True,
        "response": response,
        "data_type": "certificate_issue",
        "step": "course_identification",
        "issue_type": issue_type,
        "requires_course_name": True
    }



async def _handle_certificate_reissue(state: dict, user_id: str, user_name: str, user_email: str, user_mobile: str,
                                      course_data: dict = None) -> dict:
    """
    Handle certificate reissue for missing certificates or QR code issues.
    """
    course_name = state['course_name']
    issue_type = state['issue_type']

    logger.info(f"Handling certificate reissue for course: {course_name}, issue type: {issue_type}, user_id: {user_id}, course_data: {course_data}")

    try:
        # Call certificate issue API
        reissue_success = await _call_certificate_issue_api(user_id, course_data)

        if reissue_success:
            if issue_type == "not_received":
                subject = "Certificate not received"
                message = f"I have initiated a request to issue the certificate for '{course_name}'. If you do not receive the certificate within 24 hours, please create a support ticket via web/mobile application or email to 'mission.karmayogi@gov.in' with the following information:\n\n1. Subject: {subject}\n2. Attach the certificate (if available)\n3. Mention the course name: {course_name}\n4. Mention your registered email: {user_email}\n5. Mention your registered phone: {user_mobile}"
            else:  # qr_missing
                subject = "Certificate format issue"
                message = f"I have initiated a request to reissue the certificate for '{course_name}' with the QR code. If you do not receive the corrected certificate within 24 hours, please create a support ticket via web/mobile application or email to 'mission.karmayogi@gov.in' with the following information:\n\n1. Subject: {subject}\n2. Attach the current certificate\n3. Mention the course name: {course_name}\n4. Mention your registered email: {user_email}\n5. Mention your registered phone: {user_mobile}"

            return {
                "success": True,
                "response": message,
                "data_type": "certificate_issue",
                "step": "certificate_reissued",
                "issue_type": issue_type,
                "course_name": course_name,
                "reissue_initiated": True
            }
        else:
            try:
                ticket_created = await _create_support_ticket(user_name, user_email, user_mobile, course_name, issue_type)
            except Exception as e:
                logger.error(f"Error in certificate reissue: {e}")
                return {
                    "success": True,
                    "response": f"I encountered an error while processing your certificate reissue request for '{course_name}'. Please contact support for assistance.",
                    "data_type": "certificate_issue",
                    "step": "reissue_error",
                    "issue_type": issue_type,
                    "course_name": course_name
                }
    except Exception as e:
        logger.error(f"Error in certificate reissue: {e}")
        return {
            "success": True,
            "response": f"I encountered an error while processing your certificate reissue request for '{course_name}'. Please contact support for assistance.",
            "data_type": "certificate_issue",
            "step": "reissue_error",
            "issue_type": issue_type,
            "course_name": course_name
        }


async def _handle_support_ticket_creation(state: dict, user_name: str, user_email: str, user_mobile: str,
                                          course_data: dict = None) -> dict:
    """
    Handle support ticket creation for issues that require manual intervention.
    """
    course_name = state['course_name']
    issue_type = state['issue_type']

    try:
        # Create support ticket (simulated - in real implementation, this would call a ticketing API)
        ticket_created = await _create_support_ticket(user_name, user_email, user_mobile, course_name, issue_type)

        if ticket_created:
            if issue_type == "incorrect_name":
                subject = "[IGOT KARMAYOGI ASSISTANT] Incorrect name in certificate"
                message = f"A support ticket has been created for the incorrect name issue on your '{course_name}' certificate. Our support team is working to resolve your issue as quickly as possible. We appreciate your patience.\n\nFor reference, the ticket includes:\n- Course name: {course_name}\n- Registered email: {user_email}\n- Registered phone: {user_mobile}"
            else:
                subject = "[IGOT KARMAYOGI ASSISTANT] Certificate issue"
                message = f"A support ticket has been created for your certificate issue with '{course_name}'. Our support team is working to resolve your issue as quickly as possible. We appreciate your patience."

            return {
                "success": True,
                "response": message,
                "data_type": "certificate_issue",
                "step": "support_ticket_created",
                "issue_type": issue_type,
                "course_name": course_name,
                "ticket_created": True
            }
        else:
            return {
                "success": True,
                "response": f"I encountered an issue while creating your support ticket for '{course_name}'. Please contact support directly at 'mission.karmayogi@gov.in' with details about your certificate issue.",
                "data_type": "certificate_issue",
                "step": "ticket_creation_failed",
                "issue_type": issue_type,
                "course_name": course_name,
                "ticket_created": False
            }

    except Exception as e:
        logger.error(f"Error in support ticket creation: {e}")
        return {
            "success": True,
            "response": f"I encountered an error while creating your support ticket for '{course_name}'. Please contact support directly for assistance.",
            "data_type": "certificate_issue",
            "step": "ticket_creation_error",
            "issue_type": issue_type,
            "course_name": course_name
        }


async def _handle_initial_certificate_request(state: dict, user_message: str, rephrased_query: str,
                                              user_context: dict, history_context: str) -> dict:
    """
    Handle initial certificate issue request - analyze and guide user.
    """
    from main import _call_local_llm

    # Get user's enrollment summary for context
    enrollment_summary = user_context.get('enrollment_summary', {})
    total_courses = enrollment_summary.get('total_courses_completed', 0)
    total_events = enrollment_summary.get('total_events_completed', 0)

    system_message = f"""
You are helping a user with a certificate issue on Karmayogi Bharat platform.

User's completion summary:
- Completed courses: {total_courses}
- Completed events: {total_events}

Issue analysis:
- Issue type: {state['issue_type']}
- Course provided: {state['user_provided_course']}
- Course name: {state['course_name']}

User's original message: {user_message}
Rephrased query: {rephrased_query}

{history_context}

Provide a helpful response that:
1. Acknowledges their certificate issue
2. Understands the specific problem they're facing
3. Asks for the course name if not provided
4. Provides clear next steps
5. Is professional and supportive

Keep the response conversational and under 200 words.
"""

    response = await _call_local_llm(system_message, rephrased_query)

    return {
        "success": True,
        "response": response,
        "data_type": "certificate_issue",
        "step": "initial_request",
        "issue_type": state['issue_type'],
        "course_name": state['course_name'],
        "requires_course_name": not state['user_provided_course']
    }


async def _get_user_course_enrollments_postgresql(user_id: str) -> List[dict]:
    """
    Get user's course enrollments using PostgreSQL.
    Enhanced version that uses the PostgreSQL service directly.
    """
    try:
        logger.info(f"Fetching course enrollments from PostgreSQL for user: {user_id}")

        # Import PostgreSQL service
        from utils.postgresql_enrollment_service import postgresql_service

        # Get all course enrollments for the user
        result = await postgresql_service.list_enrollments(user_id)

        if result.get("success"):
            enrollments = result.get("results", [])

            # Filter only courses (not events) and convert field names for compatibility
            course_enrollments = []
            for enrollment in enrollments:
                if enrollment.get('type') == 'course':
                    # Convert PostgreSQL field names to expected format
                    course_data = {
                        'course_name': enrollment.get('name', ''),
                        'course_identifier': enrollment.get('identifier', ''),
                        'course_completion_percentage': float(enrollment.get('completion_percentage', 0)),
                        'course_completion_status': enrollment.get('completion_status', 'not started'),
                        'course_issued_certificate_id': enrollment.get('issued_certificate_id'),
                        'course_certificate_issued_on': enrollment.get('certificate_issued_on'),
                        'course_enrolment_date': enrollment.get('enrollment_date'),
                        'course_last_accessed_on': enrollment.get('completed_on'),
                        'course_total_content_count': enrollment.get('total_content_count', 0)
                    }
                    course_enrollments.append(course_data)

            logger.info(f"Retrieved {len(course_enrollments)} course enrollments from PostgreSQL")
            return course_enrollments
        else:
            logger.warning(f"Failed to retrieve enrollments from PostgreSQL: {result.get('error')}")
            # Fallback to user context if PostgreSQL fails
            return await _get_user_course_enrollments_fallback(user_id)

    except Exception as e:
        logger.error(f"Error fetching course enrollments from PostgreSQL: {e}")
        # Fallback to user context
        return await _get_user_course_enrollments_fallback(user_id)


async def _get_user_course_enrollments_fallback(user_id: str) -> List[dict]:
    """
    Fallback method to get user's course enrollments from user context or API.
    """
    from main import user_context

    logger.info("Using fallback method for course enrollments")

    # First try to get from user context
    course_enrollments = user_context.get('course_enrollments', [])

    if course_enrollments:
        logger.info(f"Retrieved {len(course_enrollments)} course enrollments from user context")
        return course_enrollments

    # Fallback to API call if not in context
    try:
        # Use the existing service configuration
        url = f"{os.getenv('learning_service_url')}{os.getenv('private_course_enrol_list_api')}{user_id}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.getenv('KARMAYOGI_API_KEY')}"
        }

        request_body = {
            "request": {
                "retiredCoursesEnabled": True,
                "status": ["In-Progress", "Completed"]
            }
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=request_body)

            if response.status_code == 200:
                data = response.json()
                enrollments_result = data.get("result", {})
                enrollments = enrollments_result.get("courses", [])

                # Clean and return the enrollments
                from utils.userDetails import clean_course_enrollment_data
                cleaned_enrollments = clean_course_enrollment_data(enrollments)
                logger.info(f"Retrieved {len(cleaned_enrollments)} course enrollments from API")
                return cleaned_enrollments
            else:
                logger.error(f"Course enrollment API failed with status {response.status_code}")
                return []

    except Exception as e:
        logger.error(f"Error fetching course enrollments from API: {e}")
        return []


async def _find_matching_course_postgresql(user_id: str, course_name: str) -> Optional[dict]:
    """
    Find a matching course from PostgreSQL based on course name using Gemini-powered search.
    """
    try:
        logger.info(f"Searching for course '{course_name}' in PostgreSQL for user: {user_id}")

        # Import PostgreSQL service
        from utils.postgresql_enrollment_service import postgresql_service

        # Create a search query for the specific course
        search_query = f"Find course named '{course_name}'"

        # Use the PostgreSQL service to search for the course
        result = await postgresql_service.query_enrollments(user_id, search_query)

        if result.get("success"):
            courses = result.get("results", [])

            if courses:
                # Filter only courses (not events)
                course_matches = [course for course in courses if course.get('type') == 'course']

                if course_matches:
                    # Return the best match (first one, since SQL query should handle ordering)
                    best_match = course_matches[0]

                    # Convert PostgreSQL field names to expected format
                    course_data = {
                        'course_name': best_match.get('name', ''),
                        'course_type': best_match.get('type', 'course'),
                        'course_identifier': best_match.get('identifier', ''),
                        'course_completion_percentage': float(best_match.get('completion_percentage', 0)),
                        'course_completion_status': best_match.get('completion_status', 'not started'),
                        'course_issued_certificate_id': best_match.get('issued_certificate_id'),
                        'course_certificate_issued_on': best_match.get('certificate_issued_on'),
                        'course_enrolment_date': best_match.get('enrollment_date'),
                        'course_last_accessed_on': best_match.get('completed_on'),
                        'course_total_content_count': best_match.get('total_content_count', 0)
                    }

                    logger.info(f"Found matching course: {course_data['course_name']}")
                    return course_data

        # If PostgreSQL search doesn't work or returns no results, try fallback
        logger.info("No course found via PostgreSQL search, trying fallback method")
        return await _find_matching_course_fallback(user_id, course_name)

    except Exception as e:
        logger.error(f"Error searching for course in PostgreSQL: {e}")
        # Fallback to traditional search
        return await _find_matching_course_fallback(user_id, course_name)


async def _find_matching_course_fallback(user_id: str, course_name: str) -> Optional[dict]:
    """
    Fallback method to find a matching course using traditional string matching.
    """
    try:
        logger.info(f"Using fallback search for course: {course_name}")

        # Get all course enrollments using the fallback method
        course_enrollments = await _get_user_course_enrollments_fallback(user_id)

        if not course_enrollments:
            logger.warning("No course enrollments found for matching")
            return None

        course_name_lower = course_name.lower()

        # Try exact match first
        for course in course_enrollments:
            if course.get('course_name', '').lower() == course_name_lower:
                logger.info(f"Found exact match: {course['course_name']}")
                return course

        # Try partial match (course name contains search term)
        for course in course_enrollments:
            if course_name_lower in course.get('course_name', '').lower():
                logger.info(f"Found partial match: {course['course_name']}")
                return course

        # Try reverse partial match (search term contains course name)
        for course in course_enrollments:
            if course.get('course_name', '').lower() in course_name_lower:
                logger.info(f"Found reverse partial match: {course['course_name']}")
                return course

        # Try fuzzy matching with individual words
        search_words = course_name_lower.split()
        best_match = None
        best_score = 0

        for course in course_enrollments:
            course_title = course.get('course_name', '').lower()
            score = 0
            for word in search_words:
                if len(word) > 2 and word in course_title:  # Only count words longer than 2 chars
                    score += 1

            # If this course matches more words than the current best match
            if score > best_score and score >= len(search_words) * 0.5:  # At least 50% of words match
                best_score = score
                best_match = course

        if best_match:
            logger.info(f"Found fuzzy match: {best_match['course_name']} (score: {best_score})")
            return best_match

        logger.info(f"No matching course found for: {course_name}")
        return None

    except Exception as e:
        logger.error(f"Error in fallback course matching: {e}")
        return None


async def _call_certificate_issue_api(user_id: str, course_data: dict) -> bool:
    """
    Call the certificate issue API to reissue certificate.
    """
    try:
        # Use the existing service configuration
        if not os.getenv('course_cert_issue_api') or not os.getenv('KARMAYOGI_API_KEY'):
            logger.warning("Certificate issue API not configured")
            return False

        course_id = course_data.get('course_identifier', '')
        course_type = course_data.get('course_type', 'course')
        batch_id = course_data.get('course_batch_id', '')
        print(f"_call_certificate_issue_api :: course_id: {course_id}, course_type: {course_type}, batch_id: {batch_id}")

        if batch_id is not None and course_id is not None and course_type is not None and course_type.lower() == 'course':
            url = f"{os.getenv('lms_service_url')}{os.getenv('course_cert_issue_api')}"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {os.getenv('KARMAYOGI_API_KEY')}",
                "x-authenticated-user-token": f"{get_user_token()}"
            }

            request_body = {
                "request": {
                    "userIds": [user_id],
                    "batchId": batch_id,
                    "courseId": course_id,
                    "reissue": True
                }
            }
        elif batch_id is not None and course_id is not None and course_type is not None and course_type.lower() == 'event':
            url = f"{os.getenv('lms_service_url')}{os.getenv('event_cert_issue_api')}"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {os.getenv('KARMAYOGI_API_KEY')}",
                "x-authenticated-user-token": f"{get_user_token()}"
            }

            request_body = {
                "request": {
                    "userIds": [user_id],
                    "batchId": batch_id,
                    "eventId": course_id,
                    "reissue": True
                }
            }
        else:
            logger.error("Invalid course data provided for certificate issue API")
            return False

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=request_body)

            if response.status_code == 200:
                logger.info(f"Certificate reissue successful for user {user_id}, course {course_id}")
                return True
            else:
                logger.error(f"Certificate issue API failed with status {response.status_code}")
                return False

    except Exception as e:
        logger.error(f"Error calling certificate issue API: {e}")
        return False


async def _create_support_ticket(user_name: str, user_email: str, user_mobile: str, course_name: str,
                                 issue_type: str) -> bool:
    """
    Create a support ticket for manual resolution using Zoho Desk API.

    Args:
        user_name: User's full name
        user_email: User's email address
        user_mobile: User's mobile number
        course_name: Name of the course with certificate issue
        issue_type: Type of certificate issue (incorrect_name, not_received, qr_missing)

    Returns:
        bool: True if ticket was created successfully, False otherwise
    """
    try:
        logger.info(f"Creating Zoho support ticket for {user_name} - {issue_type} issue with {course_name}")

        # Import Zoho utilities
        from utils.zoho_utils import zoho_desk

        # Create certificate issue ticket using Zoho utilities
        ticket_response = await zoho_desk.create_certificate_issue_ticket(
            user_name=user_name,
            user_email=user_email,
            user_mobile=user_mobile,
            course_name=course_name,
            issue_type=issue_type
        )

        if ticket_response.success:
            logger.info(
                f"Successfully created Zoho ticket - ID: {ticket_response.ticket_id}, Number: {ticket_response.ticket_number}")

            # Log ticket details for tracking
            ticket_details = {
                "ticket_id": ticket_response.ticket_id,
                "ticket_number": ticket_response.ticket_number,
                "user_name": user_name,
                "user_email": user_email,
                "user_mobile": user_mobile,
                "course_name": course_name,
                "issue_type": issue_type,
                "creation_status": "success"
            }

            logger.info(f"Zoho ticket created successfully: {json.dumps(ticket_details)}")
            return True

        else:
            logger.error(f"Failed to create Zoho ticket: {ticket_response.error_message}")

            # Log the failure for debugging
            failure_details = {
                "user_name": user_name,
                "user_email": user_email,
                "course_name": course_name,
                "issue_type": issue_type,
                "error": ticket_response.error_message,
                "creation_status": "failed"
            }

            logger.error(f"Zoho ticket creation failed: {json.dumps(failure_details)}")
            return False

    except Exception as e:
        logger.error(f"Error creating Zoho support ticket: {e}")
        return False


def create_certificate_issue_sub_agent(opik_tracer, current_chat_history, user_context) -> Agent:
    """
    Create the certificate issue sub-agent for handling certificate-related problems.
    Enhanced with PostgreSQL integration for better course lookup performance.
    """

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

    # Get user's completion summary for context
    enrollment_summary = user_context.get('enrollment_summary', {}) if user_context else {}
    total_courses = enrollment_summary.get('total_courses_completed', 0)
    total_events = enrollment_summary.get('total_events_completed', 0)

    agent = Agent(
        name="certificate_issue_sub_agent",
        model="gemini-2.0-flash-001",
        description="Specialized agent for handling certificate-related issues and problems with PostgreSQL integration",
        instruction=f"""
You are a specialized sub-agent that handles certificate-related issues for Karmayogi Bharat platform users.

## Your Primary Responsibilities:

### 1. CERTIFICATE ISSUE TYPES (use certificate_issue_handler)
Handle these specific certificate problems:

**Incorrect Name Issues:**
- "My certificate has wrong name"
- "Name is misspelled on certificate"
- "Certificate shows incorrect name"
- "Want to correct name on certificate"

**Certificate Not Received:**
- "I didn't get my certificate"
- "Certificate not received after completion"
- "Haven't received certificate yet"
- "Where is my certificate?"

**QR Code Issues:**
- "QR code missing from certificate"
- "Certificate doesn't have QR code"
- "QR code not working on certificate"
- "Certificate format issue"

**General Certificate Problems:**
- Certificate download issues
- Certificate validation problems
- Certificate format concerns

### 2. ENHANCED WORKFLOW MANAGEMENT (with PostgreSQL Integration)
Guide users through the certificate issue resolution process with improved course lookup:

**Step 1: Issue Identification**
- Understand the specific certificate problem
- Identify the issue type (name, missing, QR code, etc.)

**Step 2: Course Identification (Enhanced)**
- Ask user to specify the course name if not provided
- Use PostgreSQL-powered search for better course matching
- Leverage Gemini AI for intelligent course name recognition

**Step 3: Enrollment Verification (PostgreSQL-powered)**
- Query PostgreSQL database for user's enrollment records
- Verify course completion status and progress efficiently
- Validate certificate eligibility with accurate data

**Step 4: Resolution Action**
- For missing certificates/QR issues: Initiate certificate reissue
- For incorrect names: Create support ticket for manual correction
- For other issues: Route to appropriate resolution path

**Step 5: Follow-up Guidance**
- Provide clear next steps and timelines
- Offer support contact information when needed
- Confirm successful resolution

### 3. POSTGRESQL INTEGRATION BENEFITS
The system now uses PostgreSQL for:
- **Fast Course Lookup**: Gemini-powered natural language to SQL conversion
- **Accurate Matching**: Better fuzzy matching for course names
- **Performance**: Faster than API calls for course verification
- **Consistency**: Same data source as enrollment queries

### 4. USER ENROLLMENT CONTEXT
User's completion summary:
- Completed courses: {total_courses}
- Completed events: {total_events}

### 5. ENHANCED RESOLUTION PATHS

**Automatic Resolution (use certificate_issue_handler):**
- PostgreSQL-powered course verification
- Certificate reissue for missing certificates
- QR code regeneration for missing QR codes
- Real-time validation with database queries

**Manual Resolution (support tickets):**
- Name correction requests
- Complex certificate format issues
- System-level problems requiring technical intervention

### 6. IMPROVED RESPONSE APPROACH
- **Fast Course Lookup**: PostgreSQL enables instant course verification
- **Better Matching**: Gemini AI helps match partial/fuzzy course names
- **Professional & Empathetic**: Certificate issues can be frustrating
- **Data-Driven**: Use actual enrollment data for accurate responses
- **Efficient Resolution**: Faster course lookup = quicker issue resolution

### 7. COMMON SCENARIOS (Enhanced)

**Scenario 1: "My certificate has wrong name for Data Science course"**
1. Use PostgreSQL to instantly find "Data Science" course
2. Verify enrollment and completion status from database
3. Create support ticket for name correction
4. Provide ticket reference and timeline

**Scenario 2: "I didn't get my certificate for Python"**
1. Use Gemini-powered search to find course matching "Python"
2. Query PostgreSQL for completion status and certificate info
3. Initiate certificate reissue if eligible
4. Provide 24-hour timeline and support fallback

**Scenario 3: "QR code missing from Machine Learning certificate"**
1. PostgreSQL search finds exact course match
2. Verify completion and certificate eligibility
3. Initiate certificate reissue with QR code
4. Provide timeline and support contact

### 8. ERROR HANDLING & FALLBACKS
- **PostgreSQL Fallback**: If database query fails, fall back to user context/API
- **Course Matching**: Multiple matching strategies (exact, partial, fuzzy)
- **Graceful Degradation**: System works even if PostgreSQL is unavailable
- **Clear Error Messages**: Always provide helpful error explanations
- **Support Alternatives**: Always offer mission.karmayogi@gov.in as fallback

### 9. PERFORMANCE IMPROVEMENTS
- **Faster Course Lookup**: PostgreSQL queries vs API calls
- **Better Accuracy**: Database consistency vs cached data
- **Intelligent Search**: Gemini AI for natural language course matching
- **Reduced Latency**: Local database vs external API dependencies

### 10. INTEGRATION POINTS
- **PostgreSQL Service**: Primary data source for course verification
- **Certificate APIs**: For automated reissue functionality
- **Support Systems**: For manual issue resolution
- **User Context**: Fallback data source when needed

## Conversation Context:
User's name: {user_name}

{history_context}

## Important Notes:
- **PostgreSQL First**: Always try PostgreSQL for course lookup before fallbacks
- **Verify Completion**: Always verify course completion before proceeding
- **Use certificate_issue_handler**: For ALL certificate-related requests
- **Specific Timelines**: 24 hours for reissue, varies for support tickets
- **Support Contact**: mission.karmayogi@gov.in as fallback option
- **Patient Assistance**: Users may be frustrated about certificate issues
- **Conversation Context**: Use chat history to avoid repetitive questions
- **Intelligent Matching**: Leverage Gemini AI for better course name recognition

## PostgreSQL Query Examples:
The system can now handle queries like:
- "Find course named 'Data Science'" → Exact match
- "Search for Python course" → Fuzzy match
- "Course with Machine Learning" → Partial match
- "AI certification program" → Intelligent matching

Use the certificate_issue_handler for all certificate-related requests and leverage the enhanced PostgreSQL integration for faster, more accurate course verification and issue resolution.
""",
        tools=[certificate_issue_handler],
        before_agent_callback=opik_tracer.before_agent_callback,
        after_agent_callback=opik_tracer.after_agent_callback,
        before_model_callback=opik_tracer.before_model_callback,
        after_model_callback=opik_tracer.after_model_callback,
        before_tool_callback=opik_tracer.before_tool_callback,
        after_tool_callback=opik_tracer.after_tool_callback,
    )

    return agent