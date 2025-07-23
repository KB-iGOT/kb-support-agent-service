# agents/user_profile_update_sub_agent.py
import json
import logging
import re
from typing import Dict, List
from google.adk.agents import Agent
from opik import track

from utils.contentCache import invalidate_user_cache, hash_cookie, get_cached_user_details
from utils.userDetails import update_user_profile, UserDetailsError, generate_otp, verify_otp

logger = logging.getLogger(__name__)

@track(name="profile_update_tool")
async def profile_update_tool(user_message: str) -> dict:
    """Enhanced tool for handling complete profile update workflow with OTP generation and verification"""
    from main import user_context, current_chat_history, _rephrase_query_with_history

    try:
        logger.info("Processing profile update request with complete OTP flow")

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

        print(f"Original User message for profile update: {user_message}")
        # if user_message_lower has less than 6 words, rephrase it
        if len(user_message.split()) < 4:
            rephrased_query = await _rephrase_query_with_history(user_message, current_chat_history)
        else:
            rephrased_query = user_message
        print(f"Rephrased User message for profile update: {rephrased_query}")

        # Extract user profile information
        profile_data = user_context.get('profile', {})
        user_id = profile_data.get('identifier', '')
        current_name = profile_data.get('firstName', '')
        current_email = profile_data.get('profileDetails', {}).get('personalDetails', {}).get('primaryEmail', '')
        current_mobile = profile_data.get('profileDetails', {}).get('personalDetails', {}).get('mobile', '')

        print(f"profile_update_tool:: Current user profile:: {current_name}, {current_email}, {current_mobile}")

        # Analyze the workflow state
        workflow_state = await _analyze_workflow_state(rephrased_query, current_chat_history)

        logger.info(f"Workflow state: {json.dumps(workflow_state)}")

        # Handle different workflow steps
        if workflow_state['step'] == 'otp_generation':
            return await _handle_otp_generation(workflow_state, user_id, current_mobile)

        elif workflow_state['step'] == 'otp_verification':
            return await _handle_otp_verification(workflow_state, user_id, current_mobile)

        elif workflow_state['step'] == 'profile_update':
            return await _handle_profile_update(workflow_state, user_id)

        else:
            # Initial request or guidance
            return await _handle_initial_request(workflow_state, user_message, rephrased_query,
                                                 current_name, current_email, current_mobile, history_context)

    except Exception as e:
        logger.error(f"Error in enhanced profile_update_tool: {e}")
        return {"success": False, "error": str(e)}

async def _analyze_workflow_state(query: str, chat_history: List) -> dict:
    """
    Use local LLM to analyze workflow state based on query and chat history.
    """
    from main import _call_local_llm

    # Prepare chat history context
    history_context = ""
    if chat_history:
        history_context = "\nRecent conversation history:\n"
        for msg in chat_history[-4:]:
            role = "User" if msg.role == "user" else "Assistant"
            history_context += f"{role}: {msg.content}\n"

    # IMPROVED System prompt for LLM with better OTP extraction
    system_prompt = f"""
You are an expert workflow state analyzer for profile update requests in Karmayogi Bharat platform.

WORKFLOW STEP DEFINITIONS:
1. "initial" - First time user asks to update something, no workflow started yet
2. "otp_generation" - User provided update request with new value, need to send OTP to current registered number
3. "otp_verification" - OTP was sent, now user provides OTP code to verify
4. "profile_update" - OTP verified successfully, now execute the actual profile update
5. "awaiting_otp" - Waiting for user to provide OTP after it was sent
6. "awaiting_phone" - Need user's current phone number to send OTP
7. "awaiting_new_value" - Need the new value user wants to update to

STEP DETERMINATION LOGIC:
- If user requests update AND provides new value → "otp_generation" 
- If conversation shows "OTP sent" and user provides OTP code → "otp_verification"
- If conversation shows "OTP verified" → "profile_update"
- If user asks to update but no new value provided → "awaiting_new_value"
- If need current phone for OTP but not provided → "awaiting_phone"

OTP CODE EXTRACTION RULES:
- Look for numeric sequences (4-6 digits) that appear after words like "OTP", "code", "verification", "received"
- Common patterns: "OTP 123456", "code is 123456", "received OTP 123456", "the OTP 123456"
- If user mentions receiving/entering an OTP, extract the numeric code
- Set is_otp_provided: true if OTP code is found in the message

EXAMPLES:
Query: "Change my mobile number to 8073942146"
→ step: "otp_generation", otp_code: "", is_otp_provided: false

Query: "1234" (after OTP was sent)
→ step: "otp_verification", otp_code: "1234", is_otp_provided: true

Query: "I received the OTP 257689"
→ step: "otp_verification", otp_code: "257689", is_otp_provided: true

Query: "The verification code is 123456"
→ step: "otp_verification", otp_code: "123456", is_otp_provided: true

Query: "Change my email" (no new email provided)
→ step: "awaiting_new_value", otp_code: "", is_otp_provided: false

Given the query and history, output a JSON object with:
- step: (initial, otp_generation, otp_verification, profile_update, awaiting_otp, awaiting_phone, awaiting_new_value)
- update_type: (name, email, mobile, unknown)
- new_value: (string, if present)
- phone_number: (string, if present) 
- otp_code: (string, if present - extract numeric code from user message)
- is_phone_provided: (true/false)
- is_otp_provided: (true/false - true if otp_code is found and not empty)

Query: {query}
{history_context}

IMPORTANT: Always include the otp_code field in the response, even if empty string.
Respond ONLY with the JSON object.
"""

    print(f"LLM response for workflow analysis prompt: {system_prompt} -- {query}")

    # Call local LLM
    llm_response = await _call_local_llm(system_prompt, query)
    print(f"LLM response for workflow analysis: {llm_response}")

    # Parse LLM response
    try:
        state = json.loads(llm_response)

        # Ensure all required fields are present
        required_fields = ['step', 'update_type', 'new_value', 'phone_number', 'otp_code', 'is_phone_provided', 'is_otp_provided']
        for field in required_fields:
            if field not in state:
                state[field] = '' if field in ['new_value', 'phone_number', 'otp_code'] else False

        # Additional validation for OTP extraction
        if state.get('otp_code') and state['otp_code'].strip():
            state['is_otp_provided'] = True
        else:
            state['is_otp_provided'] = False

    except Exception as e:
        print(f"Error parsing LLM response: {e}")
        # Fallback to default state if parsing fails
        state = {
            'step': 'initial',
            'update_type': 'unknown',
            'new_value': '',
            'phone_number': '',
            'otp_code': '',
            'is_phone_provided': False,
            'is_otp_provided': False
        }

    return state


async def _handle_otp_generation(state: dict, user_id: str, current_mobile: str) -> dict:
    """Handle OTP generation step"""
    try:
        phone_to_use = state['phone_number'] if state['phone_number'] else current_mobile

        if not phone_to_use:
            return {
                "success": True,
                "response": "I need your mobile number to send the OTP. Please provide your registered mobile number.",
                "data_type": "profile_update",
                "step": "awaiting_phone"
            }

        logger.info(f"Generating OTP for phone: {phone_to_use}")

        # Call OTP generation API
        otp_success = await generate_otp(phone_to_use)

        if otp_success:
            return {
                "success": True,
                "response": f"🔐 An OTP has been sent to your mobile number {phone_to_use}. Please enter the OTP to proceed with the profile update.",
                "data_type": "profile_update",
                "step": "otp_sent",
                "phone_number": phone_to_use
            }
        else:
            return {
                "success": True,
                "response": f"❌ I'm sorry, but I couldn't send the OTP to {phone_to_use}. Please check your number and try again, or contact support if the issue persists.",
                "data_type": "profile_update",
                "step": "otp_generation_failed"
            }

    except Exception as e:
        logger.error(f"Error in OTP generation: {e}")
        return {
            "success": True,
            "response": "❌ There was an error generating the OTP. Please try again later or contact support.",
            "data_type": "profile_update",
            "step": "otp_generation_failed"
        }


async def _handle_otp_verification(state: dict, user_id: str, current_mobile: str) -> dict:
    """Handle OTP verification step"""
    try:
        if not state['otp_code']:
            return {
                "success": True,
                "response": "Please enter the OTP that was sent to your mobile number.",
                "data_type": "profile_update",
                "step": "awaiting_otp"
            }

        # Extract phone number from chat history if not in current state
        phone_to_verify = state['phone_number'] if state['phone_number'] else current_mobile

        logger.info(f"Verifying OTP: {state['otp_code']} for phone: {phone_to_verify}")

        # Call OTP verification API
        verification_success = await verify_otp(phone_to_verify, state['otp_code'])

        if verification_success:
            if state['new_value']:
                # We have both OTP verification and new value, proceed to update
                return await _handle_profile_update(state, user_id)
            else:
                # OTP verified, now ask for new value
                update_type = state['update_type']
                if update_type == "name":
                    response = "✅ OTP verified successfully! Please enter the new name you want to update to."
                elif update_type == "email":
                    response = "✅ OTP verified successfully! Please enter the new email address you want to update to."
                elif update_type == "mobile":
                    response = "✅ OTP verified successfully! Please enter the new mobile number you want to update to."
                else:
                    response = "✅ OTP verified successfully! Please specify what you want to update (name, email, or mobile number)."

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
                "response": "❌ The OTP verification failed. Please check the OTP and try again, or request a new OTP.",
                "data_type": "profile_update",
                "step": "otp_verification_failed"
            }

    except Exception as e:
        logger.error(f"Error in OTP verification: {e}")
        return {
            "success": True,
            "response": "❌ There was an error verifying the OTP. Please try again or contact support.",
            "data_type": "profile_update",
            "step": "otp_verification_failed"
        }


async def _handle_profile_update(state: dict, user_id: str) -> dict:
    """Handle the actual profile update after OTP verification"""
    try:
        from main import user_context, current_user_cookie

        update_type = state['update_type']
        new_value = state['new_value']

        if not new_value:
            return {
                "success": True,
                "response": f"Please provide the new {update_type} you want to update to.",
                "data_type": "profile_update",
                "step": "awaiting_new_value"
            }

        logger.info(f"Updating {update_type} to {new_value} for user {user_id}")

        # Prepare update parameters
        update_params = {}
        if update_type == "name":
            update_params['name'] = new_value
        elif update_type == "email":
            update_params['email'] = new_value
        elif update_type == "mobile":
            update_params['phone'] = new_value

        # Call the update function
        update_success = await update_user_profile(user_id, **update_params)

        if update_success:
            logger.info(f"Profile {update_type} updated successfully for user {user_id}")
            # CRITICAL: Invalidate and refresh the cache
            try:
                # Hash the current cookie
                cookie_hash = hash_cookie(current_user_cookie)

                # Invalidate the old cache entry
                cache_invalidated = await invalidate_user_cache(user_id, cookie_hash)
                logger.info(f"Cache invalidation result: {cache_invalidated}")

                # Fetch fresh user details to update the cache
                # This will call the API again and cache the updated profile
                updated_user_details, was_cached = await get_cached_user_details(
                    user_id,
                    current_user_cookie,
                    force_refresh=True  # Force refresh to get latest data
                )

                # Update the global user_context with fresh data
                user_context.clear()
                user_context.update(updated_user_details.to_dict())

                logger.info(f"Cache refreshed successfully for user {user_id} after {update_type} update")

            except Exception as cache_error:
                logger.error(f"Error refreshing cache after profile update: {cache_error}")
                # Continue with success response even if cache refresh fails
                # The update was successful, cache will be refreshed on next request

            return {
                "success": True,
                "response": f"🎉 Excellent! Your {update_type} has been successfully updated to '{new_value}'. The changes have been saved to your profile and will be reflected across the platform.",
                "data_type": "profile_update",
                "step": "update_completed",
                "update_type": update_type,
                "new_value": new_value,
                "api_success": True
            }
        else:
            return {
                "success": True,
                "response": f"❌ I apologize, but there was an error updating your {update_type}. Please try again later or contact support if the issue persists.",
                "data_type": "profile_update",
                "step": "update_failed",
                "update_type": update_type,
                "api_success": False
            }

    except UserDetailsError as e:
        logger.error(f"UserDetailsError during profile update: {e}")
        return {
            "success": True,
            "response": f"❌ There was an authentication error while updating your {update_type}. Please try again or contact support.",
            "data_type": "profile_update",
            "step": "update_failed",
            "api_success": False
        }
    except Exception as e:
        logger.error(f"Unexpected error during profile update: {e}")
        return {
            "success": True,
            "response": f"❌ An unexpected error occurred while updating your {update_type}. Please try again later or contact support.",
            "data_type": "profile_update",
            "step": "update_failed",
            "api_success": False
        }


async def _handle_initial_request(state: dict, user_message: str, rephrased_query: str,
                                  current_name: str, current_email: str, current_mobile: str,
                                  history_context: str) -> dict:
    """Handle initial profile update request"""
    from main import _call_local_llm

    system_message = f"""
## Role and Context
You are a specialized support agent for Karmayogi Bharat platform profile updates. Handle requests for updating name, email, or mobile number following the established workflow.

## User's Current Profile Information
- Name: {current_name}
- Email: {current_email}
- Mobile: {current_mobile}

## Update Request Analysis
- Update Type Detected: {state['update_type']}
- New Value Extracted: {state['new_value']}
- Phone Provided: {state['is_phone_provided']}
- Original Query: {user_message}
- Rephrased Query: {rephrased_query}

## Previous Context
{history_context}

## Response Guidelines
- Be conversational and professional
- Guide users through the verification process step by step
- Explain why OTP verification is needed for security
- If new value is already provided, acknowledge it and proceed with verification
- User their current mobile number to send OTP for verification
- Provide clear next steps at each stage

## Current Step: Initial Request
The user is making an initial request to update their profile. Guide them to the next step which is mobile number verification.

For security purposes, we need to verify their identity before making any profile changes. Use their current registered mobile number to send an OTP.

Based on the user's request, provide the appropriate response to start the verification workflow.
"""

    response = await _call_local_llm(system_message, rephrased_query)

    return {
        "success": True,
        "response": response,
        "data_type": "profile_update",
        "step": "initial_request",
        "update_type": state['update_type'],
        "new_value": state['new_value']
    }


def _detect_update_type(query: str) -> str:
    """Detect the type of profile update requested"""
    query_lower = query.lower()

    name_keywords = ['name', 'firstname', 'first name', 'full name']
    email_keywords = ['email', 'mail', 'email id', 'email address']
    mobile_keywords = ['mobile', 'phone', 'number', 'mobile number', 'phone number']

    if any(keyword in query_lower for keyword in name_keywords):
        return "name"
    elif any(keyword in query_lower for keyword in email_keywords):
        return "email"
    elif any(keyword in query_lower for keyword in mobile_keywords):
        return "mobile"
    else:
        return "unknown"


def _extract_new_value(query: str, update_type: str) -> str:
    """Extract new value from update query"""
    query_lower = query.lower()

    if update_type == "email":
        # Look for email pattern
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        match = re.search(email_pattern, query)
        if match:
            return match.group()

    elif update_type == "mobile":
        # Look for mobile number pattern (Indian format)
        mobile_patterns = [
            r'\b(\+91[\s-]?)?[6-9]\d{9}\b',  # Indian mobile numbers
            r'\b91[6-9]\d{9}\b',  # 91 prefix
            r'\b[6-9]\d{9}\b'  # 10 digit starting with 6-9
        ]

        matches = []
        for pattern in mobile_patterns:
            matches.extend(re.findall(pattern, query_lower))

        if matches:
            last_number = re.findall(r'\d{10}', matches[-1])
            return last_number[0] if last_number else ""
        else:
            return ""

    elif update_type == "name":
        # Look for name after "to" or "change name to"
        name_patterns = [
            r'(?:change|update).*?(?:name|firstname).*?to\s+([A-Za-z\s]+)',
            r'(?:name|firstname).*?to\s+([A-Za-z\s]+)',
            r'new name(?:\s+is)?\s+([A-Za-z\s]+)',
            r'name\s+(?:as|is)?\s*["\']([^"\']+)["\']'
        ]

        for pattern in name_patterns:
            match = re.search(pattern, query_lower)
            if match:
                return match.group(1).strip().title()

    return ""


def create_user_profile_update_sub_agent(opik_tracer, current_chat_history, user_context) -> Agent:
    """Create the user profile update sub-agent"""

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
        name="user_profile_update_sub_agent",
        model="gemini-2.0-flash-001",
        description="Specialized agent for handling user profile updates with OTP verification workflow",
        instruction=f"""
You are a specialized sub-agent that handles user profile update requests for Karmayogi Bharat platform, including:

## Your Primary Responsibilities:

### 1. PROFILE UPDATE WORKFLOW (use profile_update_tool)
Handle requests for updating user profile information with secure OTP verification:
- **Name changes/updates**: "I want to change my name", "Update my first name", "Change my name to John"
- **Email address changes**: "I want to update my email", "Change my email to new@example.com"
- **Mobile number changes**: "Update my mobile number", "Change my phone to 9876543210"
- **General profile modifications**: Any request to modify personal information

### 2. OTP VERIFICATION WORKFLOW
Guide users through the secure verification process:
- **OTP Generation**: Send OTP to registered mobile number
- **OTP Verification**: Verify the OTP code provided by user
- **Profile Update**: Complete the profile update after successful verification

### 3. WORKFLOW STEPS MANAGEMENT
Handle multi-step profile update process:
- **Initial Request**: Understand what user wants to update
- **Mobile Verification**: Collect mobile number for OTP
- **OTP Generation**: Generate and send OTP
- **OTP Verification**: Verify the OTP code
- **Profile Update**: Execute the actual profile update
- **Confirmation**: Confirm successful update

## Tool Usage Guidelines:

**Use profile_update_tool for ALL profile update requests including:**
- Initial profile update requests
- OTP generation requests
- OTP verification steps
- Final profile update execution
- Workflow state management

## Security and Verification:
- Always require OTP verification for profile updates
- Verify user identity before making any changes
- Follow the established OTP workflow
- Protect user privacy and sensitive information
- Handle errors gracefully with clear guidance

## Response Approach:
- **Be professional and secure** - Profile updates require verification
- **Guide step-by-step** - Walk users through the OTP workflow
- **Explain security measures** - Help users understand why verification is needed
- **Handle errors gracefully** - Provide clear guidance when issues occur
- **Confirm changes** - Always confirm successful updates
- **Use conversation history** - Maintain context throughout the workflow

## Workflow State Management:
- Track the current step in the update process
- Maintain context across multiple interactions
- Handle workflow interruptions gracefully
- Provide appropriate responses based on current state

## User Experience Principles:
- Clear explanation of each step
- Immediate feedback on user actions
- Helpful error messages and recovery guidance
- Confirmation of successful updates
- Security-first approach with user-friendly experience

## Conversation Context:
User's name: {user_name}

{history_context}

## Important Notes:
- This handles the complete profile update workflow from initial request to completion
- Always verify user identity through OTP before making changes
- Provide clear guidance at each step of the process
- Handle edge cases and errors gracefully
- Maintain security while providing good user experience

Use the profile_update_tool for all profile update related requests and guide users through the secure verification workflow.
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