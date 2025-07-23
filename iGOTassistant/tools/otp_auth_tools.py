
"""
This module contains the tools for the Karmayogi Bharat chatbot.
"""
import os
import json
import logging

import requests
from dotenv import load_dotenv
from google.adk.tools import ToolContext
from google.adk.sessions import Session

from ..config.config import API_ENDPOINTS, REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

load_dotenv()

KB_AUTH_TOKEN = os.getenv('KB_AUTH_TOKEN')


def check_channel(tool_context: ToolContext):
    """
    Verifies user channel by checking if uesr is sending message from WEB. First tool call in workflow.
    If so, no need to validate user, we can load the user details straight away.
    Args:
        tool_context: to verify the state variable.

    Returns: 
        response string.
    """
    print("INSIDE TOOL: @check_channel", )
    print('Channel state in toolcontext', tool_context.state.get("web", False))
    # print('Channel state in session', session.state.get("web", False))
    # print('Channel state in memory', tool_context.search_memory("web"))
    if tool_context.state.get("web", False):
        print(tool_context.state.get("user_id", ""))
        return "Channel is Web. User is authenticated from web, grant access to the tools. Directly load user details. User id: " + tool_context.state.get("user_id", "")
    return "Channel is Web. User is authenticated from web, grant access to the tools."


# tool function to send otp to mail/phone

def send_otp(tool_context: ToolContext):
    """
    This tool sends an OTP to the user's registered phone number.
    It automatically uses the phone number from user details if available.
    Args:
        tool_context: ToolContext to verify the previous state variables. 
    Returns:
        response string.
    """
    logger.info('tool_call: send_otp')
    
    if not tool_context.state.get('validuser', False):
        return "Validate the user first"

    # If phone number not provided or empty, try to get it from user details
    # Try to get phone from user details in state
    user_details = tool_context.state.get('userdetails', {})
    if user_details and isinstance(user_details, dict):
        phone = user_details.get('phone', '')
    
    # If still not available, try from combined user details
    if not phone or phone.strip() == "":
        combined_details = tool_context.state.get('combined_user_details', {})
        if combined_details and isinstance(combined_details, dict):
            user_details = combined_details.get('user_details', {})
            phone = user_details.get('phone', '')
    
    if not phone or phone.strip() == "":
        return "Phone number not available in user details. Please ensure user details are loaded first."

    # return "OTP sent successfully."
    # NOTE: uncomment the block for actual deployment, commented for internal tests.

    url = API_ENDPOINTS['OTP']

    payload = json.dumps({
    "request": {
       "key": phone,
       "type": "phone"
    }
    })
    headers = {
       'Content-Type': 'application/json',
       'Authorization': f'Bearer {KB_AUTH_TOKEN}'
    }

    response = requests.request("POST", url, headers=headers, data=payload, timeout=REQUEST_TIMEOUT)
    print("RESPONSE", response.json())

    if response.json()["params"]["err"]:
       return response.json()["params"]["errmsg"]

    if response.status_code == 200 and response.json()["params"]["status"] == "SUCCESS":
       return "OTP sent successfully to your registered phone number: " + phone

    return "Unable to send OTP, please try again later." + response.json()


# tool function to verify otp

def verify_otp(phone: str, code: str, tool_context: ToolContext):
    """
    This tool verifies the otp
    Args:
        tool_context: ToolContext for the validating state variables.
        phone: the number you are receiving otp for.
        code: OTP code received from user.

    Response: 
        str response.
    """
    # tool_context.state["otp_auth"] = True
    # return "Validated successfully."
    # NOTE: uncomment the block for actual deployment, commented for internal tests.
    url = API_ENDPOINTS['OTP']
    print("URL", url)

    payload = json.dumps({
    "request": {
        "key": phone,
        "type": "phone",
        "otp": code
    }
    })
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {KB_AUTH_TOKEN}'
    }

    response = requests.request("POST", url, headers=headers, data=payload, timeout=REQUEST_TIMEOUT)

    if response.status_code == 200: # and response.json()["params"]["status"] == "SUCCESS":
        tool_context.state["otp_auth"] = True
        return "OTP verification is sucessful."

    return "Couldn't verify the OTP at the moment." + response.json()
