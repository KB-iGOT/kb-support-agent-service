
"""
This module contains the tools for the Karmayogi Bharat chatbot.
"""
import os
import json
import logging

import requests
from dotenv import load_dotenv
from google.adk.tools import ToolContext

from ..config.config import API_ENDPOINTS, REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

load_dotenv()

KB_AUTH_TOKEN = os.getenv('KB_AUTH_TOKEN')

# tool function to send otp to mail/phone
def send_otp(tool_context: ToolContext, phone: str):
    """
    This tool sends an OTP to the user's email or phone number.
    It is used for user authentication and verification.
    """
    logging.info('tool_call: send_opt')
    # return "OTP sent"
    if not tool_context.state.get('validuser', False):
        return "Validate the user first"

    return "OTP sent successfully."
    # NOTE: uncomment the block for actual deployment, commented for internal tests.

    #url = API_ENDPOINTS['OTP']

    #payload = json.dumps({
    #"request": {
    #    "key": phone,
    #    "type": "phone"
    #}
    #})
    #headers = {
    #    'Content-Type': 'application/json',
    #    'Authorization': f'Bearer {KB_AUTH_TOKEN}'
    #}

    #response = requests.request("POST", url, headers=headers, data=payload, timeout=REQUEST_TIMEOUT)

    #if response.json()["params"]["err"]:
    #    return response.json()["params"]["errmsg"]

    #if response.status_code == 200 and response.json()["params"]["status"] == "SUCCESS":
    #    return "OTP sent successfully to your phone number: " + phone

    #return "Unable to send OTP, please try again later." + response.json()


# tool function to verify otp
def verify_otp(tool_context: ToolContext, phone: str, code: str):
    """
    This tool verifies the otp
    """
    # tool_context.state["otp_auth"] = True
    return "Validated successfully."
    # NOTE: uncomment the block for actual deployment, commented for internal tests.
    # url = API_ENDPOINTS['OTP']

    # payload = json.dumps({
    # "request": {
    #     "key": phone,
    #     "type": "phone",
    #     "otp": code
    # }
    # })
    # headers = {
    #     'Content-Type': 'application/json',
    #     'Authorization': f'Bearer {KB_AUTH_TOKEN}'
    # }

    # response = requests.request("POST", url, headers=headers, data=payload, timeout=REQUEST_TIMEOUT)

    # if response.status_code == 200 and response.json()["params"]["status"] == "SUCCESS":
    #     tool_context.state["otp_auth"] = True
    #     return "OTP verification is sucessful."

    # return "Couldn't verify the OTP at the moment."
