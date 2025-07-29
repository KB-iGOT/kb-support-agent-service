import json
import logging
import re
from typing import Dict, List
from google.adk.agents import Agent
from opik import track

from utils.contentCache import invalidate_user_cache, hash_cookie, get_cached_user_details
from utils.userDetails import update_user_profile, UserDetailsError, generate_otp, verify_otp

logger = logging.getLogger(__name__)

# Global workflow state tracking
_workflow_state = {}


@track(name="profile_update_tool")
async def profile_update_tool(user_message: str) -> dict:
    """Enhanced tool for handling complete profile update workflow with LLM-based analysis"""
    from main import user_context, current_chat_history

    try:
        logger.info("Processing profile update request with LLM-based workflow analysis")

        if not user_context:
            return {"success": False, "error": "User context not available"}

        # Extract user profile information
        profile_data = user_context.get('profile', {})
        user_id = profile_data.get('identifier', '')
        current_name = profile_data.get('firstName', '')
        current_email = profile_data.get('profileDetails', {}).get('personalDetails', {}).get('primaryEmail', '')
        current_mobile = profile_data.get('profileDetails', {}).get('personalDetails', {}).get('mobile', '')

        logger.info(f"profile_update_tool:: Current user profile:: {current_name}, {current_email}, {current_mobile}")

        # Get or initialize workflow state for this user
        global _workflow_state
        if user_id not in _workflow_state:
            _workflow_state[user_id] = {"step": "initial", "update_type": "unknown"}

        # Analyze the current request using LLM with chat history
        workflow_state = await _analyze_workflow_state_with_llm(
            user_message,
            current_chat_history,
            _workflow_state[user_id],
            current_mobile
        )

        logger.info(f"LLM Workflow state: {json.dumps(workflow_state)}")

        # Update the global state
        _workflow_state[user_id] = workflow_state

        # Handle different workflow steps based on update type
        update_type = workflow_state.get('update_type', 'unknown')

        if update_type == 'mobile':
            return await _handle_mobile_update_workflow(workflow_state, user_id, current_mobile)
        elif update_type in ['name', 'email']:
            # Handle name and email updates
            if workflow_state['step'] == 'otp_generation':
                return await _handle_otp_generation(workflow_state, user_id, current_mobile)
            elif workflow_state['step'] == 'otp_verification':
                return await _handle_otp_verification(workflow_state, user_id, current_mobile)
            elif workflow_state['step'] == 'profile_update':
                return await _handle_profile_update(workflow_state, user_id)
            else:
                return await _handle_initial_request(workflow_state, user_message, current_name, current_email,
                                                              current_mobile)
        else:
            return await _handle_initial_request(workflow_state, user_message, current_name, current_email,
                                                          current_mobile)

    except Exception as e:
        logger.error(f"Error in enhanced profile_update_tool: {e}")
        return {"success": False, "error": str(e)}


async def _analyze_workflow_state_with_llm(query: str, chat_history: List, current_state: dict,
                                                    current_mobile: str) -> dict:
    """Improved workflow state analysis using local LLM with better value extraction"""

    # Build chat history context
    history_context = ""
    if chat_history:
        recent_messages = chat_history[-8:] if len(chat_history) >= 4 else chat_history
        for i, msg in enumerate(recent_messages):
            role = "User" if msg.role == "user" else "Assistant"
            history_context += f"{i + 1}. {role}: {msg.content}\n"

    # Create the improved LLM prompt for workflow analysis
    llm_prompt = f"""
    You are a workflow state analyzer for user profile updates. Your job is to analyze the user query and determine the correct update type and workflow step.

    CRITICAL RULE: NEVER HALLUCINATE OR MAKE UP VALUES. ONLY EXTRACT WHAT IS EXPLICITLY STATED IN THE USER QUERY.

    CURRENT USER PROFILE:
    - Registered Mobile Number: {current_mobile}

    CONVERSATION HISTORY:
    {history_context}

    CURRENT USER QUERY: "{query}"

    CURRENT WORKFLOW STATE: {json.dumps(current_state)}

    ## CRITICAL CLASSIFICATION RULES:

    ### UPDATE TYPE DETECTION (MOST IMPORTANT):
    1. **NAME UPDATE**: If query contains words like "name", "firstname", "full name" → update_type="name"
       - Examples: "update my name", "change my name to John", "how can I update my name"

    2. **EMAIL UPDATE**: If query contains words like "email", "mail address" → update_type="email"
       - Examples: "update my email", "change email to john@example.com"

    3. **MOBILE UPDATE**: If query contains words like "mobile", "phone", "number" AND mentions mobile numbers → update_type="mobile"
       - Examples: "update my mobile", "change mobile to 9876543210"

    ### WORKFLOW STEPS:
    - **initial**: Just starting
    - **otp_generation**: Need to send OTP (for name/email updates)
    - **otp_verification**: User should provide OTP (for name/email updates)
    - **profile_update**: Ready to update profile
    - **request_current_mobile**: Ask for current mobile (mobile updates only)
    - **verify_current_mobile**: Verify provided current mobile (mobile updates only)
    - **request_new_mobile**: Ask for new mobile (mobile updates only)
    - **send_otp_to_new_mobile**: Send OTP to new mobile (mobile updates only)
    - **verify_new_mobile_otp**: Verify OTP from new mobile (mobile updates only)

    ## STEP DETERMINATION LOGIC:

    ### For NAME/EMAIL Updates:
    - If user asks "how to update name/email" → step="initial" (need to ask for new value)
    - If user provides new name/email → step="otp_generation" (send OTP to registered mobile)
    - If OTP context exists and user provides digits → step="otp_verification"

    ### For MOBILE Updates:
    - If user asks "how to update mobile" → step="initial" (need current mobile verification)
    - If user provides new mobile → step="request_current_mobile"
    - If current mobile verification in progress → step="verify_current_mobile"

    ## VALUE EXTRACTION RULES:

    ### FOR NAME UPDATES:
    - Extract new_value: the name user wants to change to
    - Examples:
      * "Change my name to John Smith" → new_value="John Smith"
      * "Update my name to Suresh Kannan" → new_value="Suresh Kannan"

    ### FOR EMAIL UPDATES:
    - Extract new_value: the email user wants to change to
    - Examples:
      * "Change my email to john@example.com" → new_value="john@example.com"

    ### FOR MOBILE UPDATES:
    - Extract current_value_provided: mobile number user claims they currently have
    - Extract new_value: mobile number user wants to change to
    - Examples:
      * "Change mobile from 8073942146 to 9597863963" → current_value_provided="8073942146", new_value="9597863963"

    ## RESPONSE FORMAT (JSON ONLY):
    {{
        "step": "one_of_the_workflow_steps_above",
        "update_type": "name" | "email" | "mobile" | "unknown",
        "current_value_provided": "extracted_current_value_or_empty",
        "new_value": "extracted_new_value_or_empty", 
        "otp_code": "extracted_otp_if_present",
        "phone_number": "phone_to_use_for_otp",
        "reasoning": "detailed_explanation_of_classification_and_decision"
    }}

    ## CLASSIFICATION EXAMPLES:

    Query: "how can i update my name"
    Response: {{
        "step": "initial",
        "update_type": "name",
        "current_value_provided": "",
        "new_value": "",
        "otp_code": "",
        "phone_number": "",
        "reasoning": "User is asking HOW to update name. This is clearly a NAME update request, not mobile. Step is initial because they haven't provided the new name yet."
    }}

    Query: "Change my name to Suresh Kannan"
    Response: {{
        "step": "otp_generation",
        "update_type": "name", 
        "current_value_provided": "",
        "new_value": "Suresh Kannan",
        "otp_code": "",
        "phone_number": "{current_mobile}",
        "reasoning": "User wants to change name to 'Suresh Kannan'. This is a NAME update. Need to send OTP to registered mobile for verification."
    }}

    Query: "update my mobile to 9876543210"
    Response: {{
        "step": "request_current_mobile",
        "update_type": "mobile",
        "current_value_provided": "",
        "new_value": "9876543210",
        "otp_code": "",
        "phone_number": "",
        "reasoning": "User wants to update mobile to 9876543210. This is a MOBILE update. Need to verify current mobile first."
    }}

    Query: "how can i update my email"
    Response: {{
        "step": "initial",
        "update_type": "email",
        "current_value_provided": "",
        "new_value": "",
        "otp_code": "",
        "phone_number": "",
        "reasoning": "User is asking HOW to update email. This is clearly an EMAIL update request. Step is initial because they haven't provided the new email yet."
    }}

ANALYZE THE QUERY AND RESPOND WITH JSON ONLY:
"""

    try:
        # Call local LLM for workflow analysis
        from main import _call_gemini_api

        llm_response = await _call_gemini_api(llm_prompt)

        # Parse LLM response
        try:
            # Clean the response to extract JSON
            json_start = llm_response.find('{')
            json_end = llm_response.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                json_str = llm_response[json_start:json_end]
                workflow_analysis = json.loads(json_str)

                logger.info(f"LLM Workflow Analysis: {workflow_analysis.get('reasoning', 'No reasoning provided')}")

                # Convert LLM analysis to our workflow state format
                return _convert_llm_analysis_to_workflow_state(workflow_analysis, current_state)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            logger.error(f"LLM Response: {llm_response}")

    except Exception as e:
        logger.error(f"Error in LLM workflow analysis: {e}")

    # Fallback to rule-based analysis if LLM fails
    logger.warning("Falling back to rule-based workflow analysis")
    return _analyze_workflow_state_rule_based(query, chat_history, current_state)


def _convert_llm_analysis_to_workflow_state(llm_analysis: dict, current_state: dict) -> dict:
    """Convert improved LLM analysis response to our workflow state format"""

    step = llm_analysis.get('step', 'initial')
    update_type = llm_analysis.get('update_type', 'unknown')
    new_value = llm_analysis.get('new_value', '').strip()
    current_value_provided = llm_analysis.get('current_value_provided', '').strip()
    otp_code = llm_analysis.get('otp_code', '').strip()
    phone_number = llm_analysis.get('phone_number', '').strip()
    reasoning = llm_analysis.get('reasoning', '').lower()

    print(f"DEBUG LLM Analysis: step={step}, type={update_type}")
    print(f"DEBUG Extracted values: current='{current_value_provided}', new='{new_value}', otp='{otp_code}'")

    # Handle name updates
    if update_type == 'name':
        if step == 'initial':  # ADD THIS CONDITION
            return {
                'step': 'initial',
                'update_type': 'name',
                'new_value': new_value,
                'current_value_provided': current_value_provided,
                'phone_number': phone_number,
                'otp_code': ''
            }
        elif step == 'otp_generation':
            return {
                'step': 'otp_generation',
                'update_type': 'name',
                'new_value': new_value,
                'current_value_provided': current_value_provided,
                'phone_number': phone_number,
                'otp_code': ''
            }
        elif step == 'otp_verification':
            return {
                'step': 'otp_verification',
                'update_type': 'name',
                'new_value': current_state.get('new_value', new_value),
                'current_value_provided': current_state.get('current_value_provided', current_value_provided),
                'phone_number': current_state.get('phone_number', phone_number),
                'otp_code': otp_code
            }
        elif step == 'profile_update':
            return {
                'step': 'profile_update',
                'update_type': 'name',
                'new_value': current_state.get('new_value', new_value),
                'current_value_provided': current_state.get('current_value_provided', current_value_provided),
                'phone_number': current_state.get('phone_number', phone_number),
                'otp_code': current_state.get('otp_code', otp_code)
            }

    # Handle email updates
    elif update_type == 'email':
        if step == 'initial':
            return {
                'step': 'initial',
                'update_type': 'email',
                'new_value': new_value,
                'current_value_provided': current_value_provided,
                'phone_number': phone_number,
                'otp_code': ''
            }
        elif step == 'otp_generation':
            return {
                'step': 'otp_generation',
                'update_type': 'email',
                'new_value': new_value,
                'current_value_provided': current_value_provided,
                'phone_number': phone_number,
                'otp_code': ''
            }
        elif step == 'otp_verification':
            return {
                'step': 'otp_verification',
                'update_type': 'email',
                'new_value': current_state.get('new_value', new_value),
                'current_value_provided': current_state.get('current_value_provided', current_value_provided),
                'phone_number': current_state.get('phone_number', phone_number),
                'otp_code': otp_code
            }
        elif step == 'profile_update':
            return {
                'step': 'profile_update',
                'update_type': 'email',
                'new_value': current_state.get('new_value', new_value),
                'current_value_provided': current_state.get('current_value_provided', current_value_provided),
                'phone_number': current_state.get('phone_number', phone_number),
                'otp_code': current_state.get('otp_code', otp_code)
            }

    # Handle mobile updates
    elif update_type == 'mobile':
        if step == 'request_current_mobile':
            return {
                'step': 'request_current_mobile_confirmation',
                'update_type': 'mobile',
                'new_mobile': new_value,
                'current_mobile': current_value_provided,
                'current_value_provided': current_value_provided,
                'new_value': new_value,
                'otp_code': '',
                'requires_current_mobile_confirmation': True
            }
        elif step == 'verify_current_mobile':
            return {
                'step': 'current_mobile_confirmed',
                'update_type': 'mobile',
                'new_mobile': current_state.get('new_mobile', new_value),
                'current_mobile': current_value_provided,
                'current_value_provided': current_value_provided,
                'new_value': current_state.get('new_value', new_value),
                'otp_code': '',
                'current_mobile_verified': True
            }
        elif step == 'send_otp_to_new_mobile':
            return {
                'step': 'send_otp_to_new_mobile',
                'update_type': 'mobile',
                'new_mobile': new_value or current_state.get('new_mobile', ''),
                'current_mobile': current_state.get('current_mobile', current_value_provided),
                'current_value_provided': current_state.get('current_value_provided', current_value_provided),
                'new_value': new_value or current_state.get('new_value', ''),
                'otp_code': '',
                'ready_for_new_mobile_otp': True
            }
        elif step == 'verify_new_mobile_otp':
            return {
                'step': 'verify_new_mobile_otp',
                'update_type': 'mobile',
                'new_mobile': current_state.get('new_mobile', new_value),
                'current_mobile': current_state.get('current_mobile', ''),
                'current_value_provided': current_state.get('current_value_provided', current_value_provided),
                'new_value': current_state.get('new_value', new_value),
                'otp_code': otp_code,
                'ready_for_verification': True
            }

    # Handle initial or unknown states
    if update_type == 'unknown':  # Only handle truly unknown types
        # Try to determine update type from extracted values
        if new_value and '@' in new_value:
            return {
                'step': 'otp_generation',
                'update_type': 'email',
                'new_value': new_value,
                'current_value_provided': current_value_provided,
                'phone_number': phone_number,
                'otp_code': ''
            }
        elif new_value and _is_valid_mobile_number(new_value):
            return {
                'step': 'request_current_mobile_confirmation',
                'update_type': 'mobile',
                'new_mobile': new_value,
                'current_mobile': current_value_provided,
                'current_value_provided': current_value_provided,
                'new_value': new_value,
                'otp_code': '',
                'requires_current_mobile_confirmation': True
            }
        elif new_value:
            return {
                'step': 'otp_generation',
                'update_type': 'name',
                'new_value': new_value,
                'current_value_provided': current_value_provided,
                'phone_number': phone_number,
                'otp_code': ''
            }

        # Default: maintain current state but update with extracted values
    updated_state = current_state.copy()
    if new_value:
        updated_state['new_value'] = new_value
    if current_value_provided:
        updated_state['current_value_provided'] = current_value_provided
    if otp_code:
        updated_state['otp_code'] = otp_code
    if phone_number:
        updated_state['phone_number'] = phone_number

    logger.info(f"Updated state with extracted values: {updated_state}")
    return updated_state


def _analyze_workflow_state_rule_based(query: str, chat_history: List, current_state: dict) -> dict:
    """Improved fallback rule-based workflow analysis with better value extraction"""

    query_lower = query.lower().strip()

    # Use improved extraction functions
    extracted_values = _extract_values_from_query(query)
    otp_code = extracted_values.get('otp_code', '')
    mobile_number = extracted_values.get('mobile_number', '')
    email = extracted_values.get('email', '')
    name = extracted_values.get('name', '')
    current_mobile = extracted_values.get('current_mobile', '')
    new_mobile = extracted_values.get('new_mobile', '')

    print(f"DEBUG Rule-based improved extraction:")
    print(f"  OTP: '{otp_code}', Mobile: '{mobile_number}', Email: '{email}', Name: '{name}'")
    print(f"  Current Mobile: '{current_mobile}', New Mobile: '{new_mobile}'")

    # Get current workflow state
    current_step = current_state.get('step', 'initial')
    update_type = current_state.get('update_type', 'unknown')

    # Check for OTP context in conversation history
    otp_context_detected = False
    if chat_history:
        recent_content = " ".join([msg.content.lower() for msg in chat_history[-2:]])
        otp_indicators = [
            "otp sent", "verification code", "enter the otp", "6-digit otp",
            "enter otp", "otp you received", "verification code to your"
        ]
        otp_context_detected = any(indicator in recent_content for indicator in otp_indicators)

    # PRIORITY 1: If OTP context detected and user provides digits, it's OTP verification
    if otp_context_detected and otp_code:
        return {
            'step': 'otp_verification',
            'update_type': update_type if update_type != 'unknown' else _detect_update_type_from_history(chat_history),
            'new_value': current_state.get('new_value', ''),
            'current_value_provided': current_state.get('current_value_provided', ''),
            'phone_number': current_state.get('phone_number', ''),
            'otp_code': otp_code
        }

    # PRIORITY 2: Detect initial update requests
    if current_step == 'initial':
        if new_mobile and current_mobile:
            return {
                'step': 'request_current_mobile_confirmation',
                'update_type': 'mobile',
                'new_mobile': new_mobile,
                'current_mobile': current_mobile,
                'current_value_provided': current_mobile,
                'new_value': new_mobile,
                'otp_code': '',
                'requires_current_mobile_confirmation': True
            }
        elif mobile_number and ('change' in query_lower or 'update' in query_lower):
            return {
                'step': 'request_current_mobile_confirmation',
                'update_type': 'mobile',
                'new_mobile': mobile_number,
                'current_mobile': '',
                'current_value_provided': '',
                'new_value': mobile_number,
                'otp_code': '',
                'requires_current_mobile_confirmation': True
            }
        elif email:
            return {
                'step': 'otp_generation',
                'update_type': 'email',
                'new_value': email,
                'current_value_provided': '',
                'phone_number': '',
                'otp_code': ''
            }
        elif name:
            return {
                'step': 'otp_generation',
                'update_type': 'name',
                'new_value': name,
                'current_value_provided': '',
                'phone_number': '',
                'otp_code': ''
            }

    # Handle ongoing workflows
    if update_type == 'mobile':
        if current_step == 'request_current_mobile_confirmation' and mobile_number:
            return {
                'step': 'current_mobile_confirmed',
                'update_type': 'mobile',
                'new_mobile': current_state.get('new_mobile', ''),
                'current_mobile': mobile_number,
                'current_value_provided': mobile_number,
                'new_value': current_state.get('new_value', ''),
                'otp_code': '',
                'current_mobile_verified': True
            }
        elif current_step in ['otp_sent_to_new_mobile', 'awaiting_new_mobile_otp'] and otp_code:
            return {
                'step': 'verify_new_mobile_otp',
                'update_type': 'mobile',
                'new_mobile': current_state.get('new_mobile', ''),
                'current_mobile': current_state.get('current_mobile', ''),
                'current_value_provided': current_state.get('current_value_provided', ''),
                'new_value': current_state.get('new_value', ''),
                'otp_code': otp_code,
                'ready_for_verification': True
            }

    elif update_type in ['name', 'email']:
        if current_step in ['otp_generation', 'otp_sent'] and otp_code:
            return {
                'step': 'otp_verification',
                'update_type': update_type,
                'new_value': current_state.get('new_value', ''),
                'current_value_provided': current_state.get('current_value_provided', ''),
                'phone_number': current_state.get('phone_number', ''),
                'otp_code': otp_code
            }

    # Default: maintain current state
    return current_state


def _extract_values_from_query(query: str) -> dict:
    """Improved value extraction from query with better pattern matching"""

    extracted = {
        'otp_code': '',
        'mobile_number': '',
        'email': '',
        'name': '',
        'current_mobile': '',
        'new_mobile': ''
    }

    # Extract OTP code (4-6 digits)
    otp_pattern = r'\b\d{4,6}\b'
    otp_matches = re.findall(otp_pattern, query.strip())
    if otp_matches:
        extracted['otp_code'] = otp_matches[-1]

    # Extract email addresses
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    email_matches = re.findall(email_pattern, query)
    if email_matches:
        extracted['email'] = email_matches[-1]

    # Extract mobile numbers (10 digits starting with 6-9)
    mobile_pattern = r'\b[6-9]\d{9}\b'
    mobile_matches = re.findall(mobile_pattern, query)

    if mobile_matches:
        if len(mobile_matches) == 1:
            extracted['mobile_number'] = mobile_matches[0]
        elif len(mobile_matches) == 2:
            # Try to determine which is current and which is new based on context
            query_lower = query.lower()
            if 'from' in query_lower and 'to' in query_lower:
                from_index = query_lower.find('from')
                to_index = query_lower.find('to')
                if from_index < to_index:
                    extracted['current_mobile'] = mobile_matches[0]
                    extracted['new_mobile'] = mobile_matches[1]
                else:
                    extracted['current_mobile'] = mobile_matches[1]
                    extracted['new_mobile'] = mobile_matches[0]
            else:
                # Default: first is current, second is new
                extracted['current_mobile'] = mobile_matches[0]
                extracted['new_mobile'] = mobile_matches[1]
        else:
            # Multiple mobile numbers, take the last one as primary
            extracted['mobile_number'] = mobile_matches[-1]

    # Extract names (improved pattern)
    name_patterns = [
        r'(?:change|update|set).*?(?:my\s+)?(?:name|firstname)\s+(?:from\s+[A-Za-z\s]+\s+)?to\s+([A-Za-z\s]+)',
        r'(?:change|update|set).*?(?:name|firstname).*?to\s+([A-Za-z\s]+)',
        r'my\s+(?:name|firstname)\s+to\s+([A-Za-z\s]+)',
        r'name\s+to\s+([A-Za-z\s]+)'
    ]

    for pattern in name_patterns:
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            # Clean up the name (remove extra words that might have been captured)
            name_words = name.split()
            # Take only words that look like name parts (alphabetic, reasonable length)
            clean_name_words = []
            for word in name_words:
                if word.isalpha() and len(word) <= 20:  # Reasonable name length
                    clean_name_words.append(word.capitalize())
                else:
                    break  # Stop at first non-name word

            if clean_name_words:
                extracted['name'] = ' '.join(clean_name_words)
                break

    return extracted


def _detect_update_type_from_history(chat_history: List) -> str:
    """Detect update type from conversation history"""
    if not chat_history:
        return 'unknown'

    history_text = " ".join([msg.content.lower() for msg in chat_history])

    if any(keyword in history_text for keyword in ['name', 'firstname']):
        return 'name'
    elif any(keyword in history_text for keyword in ['email', 'mail']):
        return 'email'
    elif any(keyword in history_text for keyword in ['mobile', 'phone']):
        return 'mobile'

    return 'unknown'


def _is_valid_mobile_number(mobile: str) -> bool:
    """Validate mobile number format"""
    if not mobile or len(mobile) != 10:
        return False

    # Must start with 6, 7, 8, or 9
    if not mobile.startswith(('6', '7', '8', '9')):
        return False

    # Must be all digits
    if not mobile.isdigit():
        return False

    return True


async def _handle_mobile_update_workflow(state: dict, user_id: str, profile_current_mobile: str) -> dict:
    """Enhanced mobile update workflow handler following exact specified steps"""

    step = state['step']
    new_mobile = state.get('new_value', '')
    current_mobile_provided = state.get('current_value_provided', '')

    global _workflow_state

    # Step 1: Ask user to enter current mobile number if not entered already
    if step == 'request_current_mobile_confirmation':
        if not current_mobile_provided:
            return {
                "success": True,
                "response": f"🔐 **Security Verification Required**\n\nTo update your mobile number to **{new_mobile}**, I need to verify your identity first.\n\n📱 Please enter your current registered mobile number to proceed.\n\n*For your security, this step is mandatory.*",
                "data_type": "profile_update",
                "step": "awaiting_current_mobile",
                "update_type": "mobile",
                "new_mobile": new_mobile
            }
        else:
            # User provided current mobile, proceed to verification
            _workflow_state[user_id]['step'] = 'verify_current_mobile'
            _workflow_state[user_id]['current_mobile'] = current_mobile_provided
            return await _handle_mobile_update_workflow(
                {**state, 'step': 'current_mobile_confirmed', 'current_mobile': current_mobile_provided},
                user_id,
                profile_current_mobile
            )

    # Step 2: Verify user entered mobile number matches registered mobile
    elif step == 'current_mobile_confirmed':
        current_mobile_provided = state.get('current_mobile', '')

        if _validate_current_mobile_against_profile(current_mobile_provided, profile_current_mobile):
            _workflow_state[user_id]['step'] = 'current_mobile_verified'
            _workflow_state[user_id]['current_mobile_verified'] = True

            # Step 3: Ask for new mobile number if not provided
            if not new_mobile:
                return {
                    "success": True,
                    "response": f"✅ **Current Mobile Verified Successfully!**\n\nYour current mobile number has been verified.\n\n📱 Now, please enter the new mobile number you want to update to.\n\nExample: 9876543210",
                    "data_type": "profile_update",
                    "step": "awaiting_new_mobile",
                    "update_type": "mobile"
                }
            else:
                # We have new mobile, proceed to send OTP
                _workflow_state[user_id]['step'] = 'send_otp_to_new_mobile'
                return await _send_otp_to_new_mobile(new_mobile, user_id)
        else:
            return {
                "success": True,
                "response": f"❌ **Mobile Verification Failed**\n\nThe mobile number you entered ({current_mobile_provided}) doesn't match our records.\n\n🔐 **Your registered mobile number is: {profile_current_mobile}**\n\nPlease enter the correct current mobile number to proceed.",
                "data_type": "profile_update",
                "step": "awaiting_current_mobile",
                "update_type": "mobile",
                "new_mobile": new_mobile
            }

    # Step 4: Send OTP to new mobile number
    elif step == 'send_otp_to_new_mobile':
        return await _send_otp_to_new_mobile(new_mobile, user_id)

    # Step 5: Ask user to input the OTP (handled by OTP sending function)
    elif step == 'otp_sent_to_new_mobile':
        return {
            "success": True,
            "response": f"🔐 **OTP Sent Successfully!**\n\nI've sent a verification code to your new mobile number **{new_mobile}**.\n\n📱 **Please enter the 6-digit OTP** you received to complete the mobile number update.\n\n⏱️ The OTP is valid for 10 minutes.",
            "data_type": "profile_update",
            "step": "awaiting_new_mobile_otp",
            "update_type": "mobile",
            "new_mobile": new_mobile
        }

    # Step 6: Verify OTP and Step 7: Update profile if successful
    elif step == 'verify_new_mobile_otp':
        return await _verify_otp_and_update_mobile(state, user_id)

    else:
        # Fallback to initial step
        return {
            "success": True,
            "response": f"I understand you want to update your mobile number. Let me guide you through the secure process.\n\n🔐 **Step 1: Current Mobile Verification**\n\nPlease enter your current registered mobile number to proceed.",
            "data_type": "profile_update",
            "step": "awaiting_current_mobile",
            "update_type": "mobile",
            "new_mobile": new_mobile
        }


async def _send_otp_to_new_mobile(new_mobile: str, user_id: str) -> dict:
    """Send OTP to new mobile number with validation"""
    try:
        # Validate mobile number format
        if not _is_valid_mobile_number(new_mobile):
            return {
                "success": True,
                "response": "❌ **Invalid Mobile Number Format**\n\nPlease provide a valid 10-digit mobile number starting with 6, 7, 8, or 9.\n\n📱 Example: 9876543210",
                "data_type": "profile_update",
                "step": "awaiting_valid_new_mobile"
            }

        logger.info(f"Sending OTP to new mobile: {new_mobile}")

        # Generate and send OTP
        otp_success = await generate_otp(new_mobile)

        if otp_success:
            global _workflow_state
            _workflow_state[user_id]['step'] = 'otp_sent_to_new_mobile'
            _workflow_state[user_id]['new_mobile'] = new_mobile

            return {
                "success": True,
                "response": f"🔐 **OTP Sent Successfully!**\n\nI've sent a verification code to your new mobile number **{new_mobile}**.\n\n📱 **Please enter the 6-digit OTP** you received to complete the mobile number update.\n\n⏱️ The OTP is valid for 10 minutes.",
                "data_type": "profile_update",
                "step": "awaiting_new_mobile_otp",
                "update_type": "mobile",
                "new_mobile": new_mobile
            }
        else:
            return {
                "success": True,
                "response": f"❌ **OTP Sending Failed**\n\nI couldn't send the OTP to **{new_mobile}**.\n\n**Possible reasons:**\n• Network connectivity issues\n• Invalid mobile number\n• SMS service temporarily unavailable\n\nPlease verify the mobile number and try again.",
                "data_type": "profile_update",
                "step": "otp_generation_failed"
            }

    except Exception as e:
        logger.error(f"Error sending OTP to new mobile: {e}")
        errmsg = ""
        try:
            # If e has a response attribute with JSON
            if hasattr(e, "response") and e.response is not None:
                data = e.response.json()
                errmsg = data.get("params", {}).get("errmsg", "")
            else:
                errmsg = str(e)
        except Exception:
            errmsg = str(e)
        return {
            "success": True,
            "response": "❌ **Technical Error**\n\nThere was an error sending the OTP: {errmsg}. Please try again in a few moments",
            "data_type": "profile_update",
            "step": "error"
        }


async def _verify_otp_and_update_mobile(state: dict, user_id: str) -> dict:
    """Verify OTP and update mobile number if successful"""
    try:
        otp_code = state.get('otp_code', '').strip()
        new_mobile = state.get('new_mobile', '').strip()

        # Validate inputs
        if not otp_code:
            return {
                "success": True,
                "response": "📱 **Enter OTP Code**\n\nPlease enter the 6-digit OTP that was sent to your new mobile number.\n\n⏱️ If you didn't receive it, please wait a few minutes or request a new OTP.",
                "data_type": "profile_update",
                "step": "awaiting_new_mobile_otp"
            }

        if not new_mobile:
            return {
                "success": True,
                "response": "❌ **Session Error**\n\nNew mobile number not found in session. Please start the update process again.",
                "data_type": "profile_update",
                "step": "error"
            }

        logger.info(f"Verifying OTP: {otp_code} for new mobile: {new_mobile}")

        # Step 6: Verify OTP
        verification_success = await verify_otp(new_mobile, otp_code)

        if verification_success:
            # Step 7: OTP verified successfully - update profile with API call
            return await _execute_mobile_profile_update(user_id, new_mobile)
        else:
            return {
                "success": True,
                "response": "❌ **OTP Verification Failed**\n\nThe OTP you entered is incorrect or has expired.\n\n**Please try again:**\n• Check the 6-digit code carefully\n• Make sure you're entering the latest OTP\n• OTP expires in 10 minutes\n\nIf you need a new OTP, please start the process again.",
                "data_type": "profile_update",
                "step": "otp_verification_failed"
            }

    except Exception as e:
        logger.error(f"Error verifying OTP: {e}")
        errmsg = ""
        try:
            # If e has a response attribute with JSON
            if hasattr(e, "response") and e.response is not None:
                data = e.response.json()
                errmsg = data.get("params", {}).get("errmsg", "")
            else:
                errmsg = str(e)
        except Exception:
            errmsg = str(e)

        return {
            "success": True,
            "response": f"❌ **Technical Error**\n\nThere was an error verifying the OTP: {errmsg}. Please try again.",
            "data_type": "profile_update",
            "step": "otp_verification_failed"
        }


async def _execute_mobile_profile_update(user_id: str, new_mobile: str) -> dict:
    """Execute mobile profile update API call"""
    try:
        from main import user_context, current_user_cookie

        logger.info(f"Updating mobile number to {new_mobile} for user {user_id}")

        # Execute the profile update API call
        update_success = await update_user_profile(user_id, phone=new_mobile)

        if update_success:
            logger.info(f"Mobile number updated successfully for user {user_id}")

            # Clear workflow state
            global _workflow_state
            if user_id in _workflow_state:
                del _workflow_state[user_id]

            # Refresh user cache
            try:
                cookie_hash = hash_cookie(current_user_cookie)
                cache_invalidated = await invalidate_user_cache(user_id, cookie_hash)
                logger.info(f"Cache invalidation result: {cache_invalidated}")

                # Fetch fresh user details
                updated_user_details, was_cached = await get_cached_user_details(
                    user_id, current_user_cookie, force_refresh=True
                )

                # Update global user_context
                user_context.clear()
                user_context.update(updated_user_details.to_dict())

                logger.info(f"Cache refreshed successfully for user {user_id} after mobile update")

            except Exception as cache_error:
                logger.error(f"Error refreshing cache after mobile update: {cache_error}")

            return {
                "success": True,
                "response": f"🎉 **Mobile Number Updated Successfully!**\n\nYour mobile number has been updated to **{new_mobile}**.\n\n✅ **Update Complete!** Your profile has been updated with the new mobile number.\n\n📱 You can now use **{new_mobile}** for all future authentications.",
                "data_type": "profile_update",
                "step": "update_completed",
                "update_type": "mobile",
                "new_value": new_mobile,
                "api_success": True
            }
        else:
            return {
                "success": True,
                "response": "❌ **Profile Update Failed**\n\nI apologize, but there was an error updating your mobile number in the system.\n\n**What you can do:**\n• Try again in a few minutes\n• Contact support if the issue persists\n• Your current mobile number remains unchanged\n\nError details have been logged for our technical team to investigate.",
                "data_type": "profile_update",
                "step": "update_failed",
                "update_type": "mobile",
                "api_success": False
            }

    except Exception as e:
        logger.error(f"Error during mobile update: {e}")
        return {
            "success": True,
            "response": "❌ **Technical Error**\n\nAn unexpected error occurred while updating your mobile number.\n\n**Your mobile number remains unchanged.**\n\nPlease try again later or contact support if the issue persists.",
            "data_type": "profile_update",
            "step": "update_failed",
            "api_success": False
        }


async def _handle_otp_generation(state: dict, user_id: str, current_mobile: str) -> dict:
    """Handle OTP generation step for name/email updates"""
    try:
        update_type = state.get('update_type', '')
        new_value = state.get('new_value', '')

        phone_to_use = current_mobile  # Always use registered mobile for name/email updates

        if not phone_to_use:
            return {
                "success": True,
                "response": "❌ **Mobile Number Required**\n\nI need your registered mobile number to send the OTP. Please contact support if you're having issues.",
                "data_type": "profile_update",
                "step": "awaiting_phone"
            }

        logger.info(f"Generating OTP for {update_type} update, phone: {phone_to_use}")

        # Step 1: Send OTP to registered mobile number
        otp_success = await generate_otp(phone_to_use)

        if otp_success:
            # Update workflow state
            global _workflow_state
            _workflow_state[user_id]['step'] = 'otp_sent'
            _workflow_state[user_id]['phone_number'] = phone_to_use

            return {
                "success": True,
                "response": f"🔐 **OTP Sent Successfully!**\n\nTo update your {update_type} to **'{new_value}'**, I've sent a verification code to your registered mobile number **{phone_to_use}**.\n\n📱 **Please enter the 6-digit OTP** you received to proceed with the {update_type} update.\n\n⏱️ The OTP is valid for 10 minutes.",
                "data_type": "profile_update",
                "step": "otp_sent",
                "phone_number": phone_to_use,
                "update_type": update_type
            }
        else:
            return {
                "success": True,
                "response": f"❌ **OTP Sending Failed**\n\nI couldn't send the OTP to your registered mobile number **{phone_to_use}**.\n\n**Possible reasons:**\n• Network connectivity issues\n• SMS service temporarily unavailable\n\nPlease try again in a few moments or contact support if the issue persists.",
                "data_type": "profile_update",
                "step": "otp_generation_failed"
            }

    except Exception as e:
        logger.error(f"Error in OTP generation: {e}")
        errmsg = ""
        try:
            # If e has a response attribute with JSON
            if hasattr(e, "response") and e.response is not None:
                data = e.response.json()
                errmsg = data.get("params", {}).get("errmsg", "")
            else:
                errmsg = str(e)
        except Exception:
            errmsg = str(e)
        return {
            "success": True,
            "response": "❌ **Technical Error**\n\nThere was an error sending the OTP: {errmsg}. Please try again in a few moments",
            "data_type": "profile_update",
            "step": "otp_generation_failed"
        }


async def _handle_otp_verification(state: dict, user_id: str, current_mobile: str) -> dict:
    """Handle OTP verification step for name/email updates"""
    try:
        update_type = state.get('update_type', '')
        new_value = state.get('new_value', '')
        otp_code = state.get('otp_code', '')

        # Step 2: Ask user to enter the OTP
        if not otp_code:
            return {
                "success": True,
                "response": f"📱 **Enter OTP Code**\n\nPlease enter the 6-digit OTP that was sent to your registered mobile number **{current_mobile}** to proceed with updating your {update_type}.\n\n⏱️ The OTP is valid for 10 minutes.",
                "data_type": "profile_update",
                "step": "awaiting_otp",
                "update_type": update_type
            }

        phone_to_verify = current_mobile

        logger.info(f"Verifying OTP: {otp_code} for {update_type} update, phone: {phone_to_verify}")

        # Step 3: Verify the OTP entered by the user
        verification_success = await verify_otp(phone_to_verify, otp_code)

        if verification_success:
            logger.info(f"OTP verified successfully for {update_type} update")

            # Update workflow state
            global _workflow_state
            _workflow_state[user_id]['step'] = 'otp_verified'
            _workflow_state[user_id]['otp_verified'] = True

            if new_value:
                # We have both OTP verification and new value, proceed to update
                return await _handle_profile_update(state, user_id)
            else:
                # OTP verified, now ask for new value
                if update_type == "name":
                    response = "✅ **OTP Verified Successfully!**\n\nYour identity has been verified. Please enter the new name you want to update to."
                elif update_type == "email":
                    response = "✅ **OTP Verified Successfully!**\n\nYour identity has been verified. Please enter the new email address you want to update to."
                else:
                    response = "✅ **OTP Verified Successfully!**\n\nYour identity has been verified. Please specify what you want to update."

                return {
                    "success": True,
                    "response": response,
                    "data_type": "profile_update",
                    "step": "otp_verified",
                    "update_type": update_type
                }
        else:
            return {
                "success": True,
                "response": "❌ **OTP Verification Failed**\n\nThe OTP you entered is incorrect or has expired.\n\n**Please try again:**\n• Check the 6-digit code carefully\n• Make sure you're entering the latest OTP\n• OTP expires in 10 minutes\n\nIf you need a new OTP, please start the process again.",
                "data_type": "profile_update",
                "step": "otp_verification_failed"
            }

    except Exception as e:
        logger.error(f"Error in OTP verification: {e}")
        errmsg = ""
        try:
            # If e has a response attribute with JSON
            if hasattr(e, "response") and e.response is not None:
                data = e.response.json()
                errmsg = data.get("params", {}).get("errmsg", "")
            else:
                errmsg = str(e)
        except Exception:
            errmsg = str(e)

        return {
            "success": True,
            "response": f"❌ **Technical Error**\n\nThere was an error verifying the OTP: {errmsg}. Please try again.",
            "data_type": "profile_update",
            "step": "otp_verification_failed"
        }


async def _handle_profile_update(state: dict, user_id: str) -> dict:
    """Handle the actual profile update after OTP verification for name/email updates"""
    try:
        from main import user_context, current_user_cookie

        update_type = state['update_type']
        new_value = state['new_value']

        if not new_value:
            return {
                "success": True,
                "response": f"📝 **Enter New {update_type.title()}**\n\nPlease provide the new {update_type} you want to update to.",
                "data_type": "profile_update",
                "step": "awaiting_new_value"
            }

        logger.info(f"Updating {update_type} to '{new_value}' for user {user_id}")

        # Prepare update parameters
        update_params = {}
        if update_type == "name":
            update_params['name'] = new_value
        elif update_type == "email":
            update_params['email'] = new_value

        # Step 4: If OTP verification is successful, invoke the profile update API
        update_success = await update_user_profile(user_id, **update_params)

        if update_success:
            logger.info(f"Profile {update_type} updated successfully for user {user_id}")

            # Clear workflow state
            global _workflow_state
            if user_id in _workflow_state:
                del _workflow_state[user_id]

            # Invalidate and refresh cache
            try:
                cookie_hash = hash_cookie(current_user_cookie)
                cache_invalidated = await invalidate_user_cache(user_id, cookie_hash)
                logger.info(f"Cache invalidation result: {cache_invalidated}")

                updated_user_details, was_cached = await get_cached_user_details(
                    user_id, current_user_cookie, force_refresh=True
                )

                user_context.clear()
                user_context.update(updated_user_details.to_dict())

                logger.info(f"Cache refreshed successfully for user {user_id} after {update_type} update")

            except Exception as cache_error:
                logger.error(f"Error refreshing cache after profile update: {cache_error}")

            return {
                "success": True,
                "response": f"🎉 **{update_type.title()} Updated Successfully!**\n\nYour {update_type} has been updated to **'{new_value}'**.\n\n✅ **Update Complete!** Your profile has been updated successfully.\n\n📝 The change is now active in your account.",
                "data_type": "profile_update",
                "step": "update_completed",
                "update_type": update_type,
                "new_value": new_value,
                "api_success": True
            }
        else:
            return {
                "success": True,
                "response": f"❌ **Profile Update Failed**\n\nI apologize, but there was an error updating your {update_type} in the system.\n\n**What you can do:**\n• Try again in a few minutes\n• Contact support if the issue persists\n• Your current {update_type} remains unchanged\n\nError details have been logged for our technical team to investigate.",
                "data_type": "profile_update",
                "step": "update_failed",
                "update_type": update_type,
                "api_success": False
            }

    except Exception as e:
        logger.error(f"Error during profile update: {e}")
        return {
            "success": True,
            "response": f"❌ **Technical Error**\n\nAn unexpected error occurred while updating your {update_type}.\n\n**Your {update_type} remains unchanged.**\n\nPlease try again later or contact support if the issue persists.",
            "data_type": "profile_update",
            "step": "update_failed",
            "api_success": False
        }


async def _handle_initial_request(state: dict, user_message: str, current_name: str, current_email: str,
                                  current_mobile: str) -> dict:
    """Handle initial profile update request - enhanced"""

    update_type = state.get('update_type', 'unknown')
    new_value = state.get('new_mobile', '') or state.get('new_value', '')

    # Handle specific update types when user asks "how to" without providing new value
    if update_type == 'name':
        if new_value:
            return {
                "success": True,
                "response": f"I understand you want to update your name to **'{new_value}'**.\n\n🔐 **Security Verification Required**\n\nFor your security, I need to send an OTP to your registered mobile number for verification.",
                "data_type": "profile_update",
                "step": "ready_for_otp_generation",
                "update_type": "name",
                "new_value": new_value
            }
        else:
            # User asks "how can I change my name" - guide them to provide new name
            return {
                "success": True,
                "response": f"I can help you update your name.\n\n📝 **Current name:** {current_name}\n\nPlease tell me what you'd like to change your name to.\n\n**Example:** \"Change my name to John Smith\"",
                "data_type": "profile_update",
                "step": "collect_new_name",
                "update_type": "name"
            }

    elif update_type == 'email':
        if new_value:
            return {
                "success": True,
                "response": f"I understand you want to update your email to **'{new_value}'**.\n\n🔐 **Security Verification Required**\n\nFor your security, I need to send an OTP to your registered mobile number for verification.",
                "data_type": "profile_update",
                "step": "ready_for_otp_generation",
                "update_type": "email",
                "new_value": new_value
            }
        else:
            return {
                "success": True,
                "response": f"I can help you update your email address.\n\n📧 **Current email:** {current_email}\n\nPlease provide the new email address you'd like to set.\n\n**Example:** \"Change my email to john@example.com\"",
                "data_type": "profile_update",
                "step": "collect_new_email",
                "update_type": "email"
            }

    elif update_type == 'mobile':
        if new_value:
            return {
                "success": True,
                "response": f"I understand you want to update your mobile number to **{new_value}**.\n\n🔐 **Security Process Required**\n\nFor your security, I need to verify your identity first by confirming your current mobile number.",
                "data_type": "profile_update",
                "step": "initial_mobile_request",
                "update_type": "mobile",
                "new_mobile": new_value
            }
        else:
            return {
                "success": True,
                "response": f"I can help you update your mobile number.\n\n📱 **Current mobile:** {current_mobile}\n\nPlease provide the new mobile number you'd like to set.\n\n**Example:** \"Change my mobile to 9876543210\"",
                "data_type": "profile_update",
                "step": "collect_new_mobile",
                "update_type": "mobile"
            }

    # Fallback for unknown update type
    return {
        "success": True,
        "response": "I'd be happy to help you update your profile information.\n\n📝 Please specify what you'd like to update:\n• **Name** - Change your display name\n• **Email address** - Update your email\n• **Mobile number** - Change your phone number\n\nPlease tell me which one you'd like to update and provide the new value.",
        "data_type": "profile_update",
        "step": "awaiting_update_details"
    }


# Utility functions
def _extract_mobile_number(text: str) -> str:
    """Enhanced mobile number extraction"""
    # Remove spaces and common separators
    cleaned_text = re.sub(r'[\s\-\(\)]+', '', text)

    # Look for 10-digit numbers starting with 6-9
    patterns = [
        r'\b[6-9]\d{9}\b',  # Standard 10-digit
        r'\+91[6-9]\d{9}',  # With country code
        r'91[6-9]\d{9}'  # With country code (no +)
    ]

    for pattern in patterns:
        matches = re.findall(pattern, cleaned_text)
        if matches:
            # Extract just the 10-digit number
            number = matches[-1]
            if number.startswith('+91'):
                return number[3:]
            elif number.startswith('91') and len(number) == 12:
                return number[2:]
            else:
                return number

    return ""


def _extract_otp_code(text: str) -> str:
    """Extract OTP code from text"""
    # Look for 4-6 digit numbers
    otp_pattern = r'\b\d{4,6}\b'
    matches = re.findall(otp_pattern, text.strip())
    return matches[-1] if matches else ""


def _extract_new_value_from_query(query: str, keywords: List[str]) -> str:
    """Extract new value from query for name/email updates"""
    query_lower = query.lower()

    # Patterns to extract new values
    for keyword in keywords:
        patterns = [
            rf'change.*?{keyword}.*?to\s+([^,\n]+)',
            rf'update.*?{keyword}.*?to\s+([^,\n]+)',
            rf'set.*?{keyword}.*?to\s+([^,\n]+)',
            rf'modify.*?{keyword}.*?to\s+([^,\n]+)',
            # Additional patterns for name specifically
            rf'change my {keyword} to\s+([^,\n]+)',
            rf'update my {keyword} to\s+([^,\n]+)',
            rf'my {keyword} to\s+([^,\n]+)',
            # Pattern to catch "change my name to Suresh Kannan"
            rf'change.*?my.*?{keyword}.*?to\s+([^,\n]+)',
            # Pattern for direct name mention
            rf'{keyword} to\s+([^,\n]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, query_lower)
            if match:
                extracted_value = match.group(1).strip()
                # For names, capitalize properly
                if keyword in ['name', 'firstname']:
                    # Split by spaces and capitalize each word
                    words = extracted_value.split()
                    capitalized_words = [word.capitalize() for word in words]
                    return ' '.join(capitalized_words)
                return extracted_value

    # If no patterns match, try a simpler approach for names
    if 'name' in keywords or 'firstname' in keywords:
        # Look for pattern like "change my name to Suresh Kannan"
        name_pattern = r'(?:change|update|set|modify).*?(?:my\s+)?(?:name|firstname)\s+to\s+([A-Za-z\s]+)'
        match = re.search(name_pattern, query, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            # Capitalize each word
            return ' '.join(word.capitalize() for word in name.split())

    return ""


def _validate_current_mobile_against_profile(provided_mobile: str, profile_mobile: str) -> bool:
    """Validate if the provided current mobile matches the profile mobile"""
    # Convert to string and check if both are valid
    provided_str = str(provided_mobile) if provided_mobile is not None else ""
    profile_str = str(profile_mobile) if profile_mobile is not None else ""

    if not provided_str or not profile_str:
        return False

    # Clean both numbers (remove spaces, dashes, etc.)
    provided_clean = re.sub(r'[\s\-\(\)]+', '', provided_str)
    profile_clean = re.sub(r'[\s\-\(\)]+', '', profile_str)

    # Handle country code variations
    if provided_clean.startswith('+91'):
        provided_clean = provided_clean[3:]
    elif provided_clean.startswith('91') and len(provided_clean) == 12:
        provided_clean = provided_clean[2:]

    if profile_clean.startswith('+91'):
        profile_clean = profile_clean[3:]
    elif profile_clean.startswith('91') and len(profile_clean) == 12:
        profile_clean = profile_clean[2:]

    return provided_clean == profile_clean


def _is_valid_mobile_number(mobile: str) -> bool:
    """Validate mobile number format"""
    if not mobile or len(mobile) != 10:
        return False

    # Must start with 6, 7, 8, or 9
    if not mobile.startswith(('6', '7', '8', '9')):
        return False

    # Must be all digits
    if not mobile.isdigit():
        return False

    return True


def create_user_profile_update_sub_agent(opik_tracer, current_chat_history, user_context) -> Agent:
    """Create the enhanced user profile update sub-agent"""

    # Build chat history context for LLM
    history_context = ""
    if current_chat_history:
        history_context = "\n\nRECENT CONVERSATION HISTORY:\n"
        for msg in current_chat_history[-8:]:  # Last 3 exchanges
            role = "User" if msg.role == "user" else "Assistant"
            content = msg.content[:150] + "..." if len(msg.content) > 150 else msg.content
            history_context += f"{role}: {content}\n"
        history_context += "\nUse this context to provide more relevant and personalized responses.\n"

    user_name = user_context.get('profile', {}).get('firstName', 'User') if user_context else 'User'

    agent = Agent(
        name="user_profile_update_sub_agent",
        model="gemini-2.0-flash-001",
        description="Enhanced specialized agent for handling user profile updates with LLM-based workflow analysis and OTP verification",
        instruction=f"""
You are an enhanced specialized sub-agent that handles user profile update requests for Karmayogi Bharat platform.

## Your Enhanced Responsibilities:

### Name/Email Updates (Standard Security):
1. **OTP Generation**: Send OTP to current registered mobile number
2. **OTP Verification**: Verify the OTP code provided by user  
3. **Profile Update**: Complete the profile update after successful verification

### Mobile Number Updates (Enhanced Security):
1. **Current Mobile Verification**: Ask and verify user's current mobile number
2. **New Mobile Collection**: Get the new mobile number from user
3. **New Mobile OTP**: Send OTP to the NEW mobile number for ownership verification
4. **OTP Verification**: Verify the OTP sent to new mobile number
5. **Profile Update**: Execute the mobile number update after successful verification


## Supported Input Formats:
- "Change my name to Jaya Prakash" (name update with OTP to registered mobile)
- "Update my name from SureshKannan to Suresh Kannan" (name update)
- "Update my mobile number to 8546972130" (mobile update with current mobile verification)
- "Change my mobile number from 9597863963 to 8073942146" (mobile update)
- "Update my email to john@example.com" (email update with OTP to registered mobile)

## Tool Usage:
**CRITICAL: Use profile_update_tool for ALL user inputs in profile update workflows**
- Every user response should trigger a profile_update_tool call
- Never respond directly without calling the tool first
- The tool manages the complete workflow state and determines next steps using LLM analysis

## Response Guidelines:
- Be professional and guide users step-by-step
- Explain security measures clearly
- Handle errors gracefully with clear guidance
- Confirm successful updates with detailed feedback
- Use conversation history for context

## User Context:
User's name: {user_name}
{history_context}

## Important Notes:
- Mobile updates require verification of BOTH current and new mobile numbers
- Name/Email updates only require current mobile verification (OTP sent to registered mobile)
- Always verify user identity before making changes
- Provide clear guidance at each step
- Handle workflow interruptions gracefully
- LLM analyzes chat history to make intelligent workflow decisions

Use the profile_update_tool for ALL user messages in profile update workflows. Always call the tool first to determine the appropriate response and next workflow step. Never respond directly without calling the tool.
""",
        tools=[profile_update_tool],
        before_agent_callback=opik_tracer.before_agent_callback,
        after_agent_callback=opik_tracer.after_agent_callback,
        before_model_callback=opik_tracer.before_model_callback,
        after_model_callback=opik_tracer.after_model_callback,
        before_tool_callback=opik_tracer.before_tool_callback,
        after_tool_callback=opik_tracer.after_tool_callback,
    )

    return agent