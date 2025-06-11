"""
This module contains the tools for the Karmayogi Bharat chatbot.
"""
import os
import json
import logging

import requests
from dotenv import load_dotenv
from google.adk.tools import ToolContext

from ..config.config import REQUEST_TIMEOUT, ZOHO_URI


logger = logging.getLogger(__name__)

load_dotenv()

ZOHO_AUTH_TOKEN = os.getenv('ZOHO_AUTH_TOKEN')
ZOHO_REFRESH_TOKEN_URL = os.getenv('ZOHO_REFRESH_TOKEN_URL')
COOKIES = os.getenv('COOKIES')

def refresh_auth_token():
    """reload the auth token for zoho ticket creation"""
    payload = {}
    headers = {
        'Cookie': COOKIES,
    }

    response = requests.request("POST", ZOHO_REFRESH_TOKEN_URL,
                                headers=headers,
                                data=payload,
                                timeout=REQUEST_TIMEOUT)

    if not response.status_code == 200:
        return None

    return response.json()['access_token']


def create_support_ticket_tool(tool_context: ToolContext, reason: str, description: str):
    """
    Tool function to create a support ticket.  This function can be integrated
    into a larger agent framework.  It follows this scenario:

    1. Please note that you should not create a ticket with same reason
        multiple times with same user in same session.
    2. Only create a ticket if user is authenticated and registered.
    3. If user is not authenticated, inform them that
        they need to authenticate first before creating ticket.
    4. If user is authenticated, ask for the issue description and create a ticket for the user.
    5. Provide the ticket number and inform the user that they will be contacted by support team.

    Case:
    [User] I want to raise an issue/ticket
    [Assistant] Sure, please let me know the reason
    [User] I am.. ....... ...... ...
    [Assistant] I am creating a ticket for you
    [system] create a support mail with the user input reason
    [Assistant] Support Ticket has been created. Please wait for support team to revert

    Args:
        reason: The user's input string.
        description : summerized last 5 messages of the conversation,
            which will be used to create the ticket.
        ** make sure that description has last five message exchanges.
        ** don't ask user for the five messages, just pass them from conversation history

    Returns:
        A string indicating the result of the operation.
    """

    userdetails = tool_context.state.get('userdetails', None)

    if not userdetails:
        return "Couldn't load the user details, for creating the tickets."

    payload = json.dumps({
        "entitySkills": [],
        "subCategory": "",
        "cf": {
            "cf_jira_id": None,
            "cf_categories": None,
            "cf_name": None,
            "cf_current_designation": None,
            "cf_ministry_state": None,
            "cf_checkbox_1": "false",
            "cf_department_name": None,
            "cf_working_team": None,
            "cf_closed_fate": None,
            "cf_cadre_of_the_employee": None,
            "cf_checkbox": "false",
            "cf_categories_1": None,
            "cf_message": None,
            "cf_severity": "Sev 3",
            "cf_modules_type": None,
            "cf_sub_categories": None,
            "cf_organization": None,
            "cf_attachment": None,
            "cf_source": None,
            "cf_requestor": None,
            "cf_do_not_merge": "false",
            "cf_sub_cadre_of_the_employee": None
        },
        "productId": "",
        "contact": {
            "firstName": userdetails.firstName,
            "lastName": userdetails.lastName,
            "email": userdetails.primaryEmail,
            "phone": userdetails.phone
        },
        "subject": reason,
        "departmentId": "120349000000010772",
        "department": {
            "id": "120349000000010772",
            "name": "Karmayogi Bharat"
        },
        "channel": "Bot",
        "description": description,
        "language": "English",
        "priority": "P3",
        "classification": "",
        "phone": userdetails.phone,
        "category": "",
        "email": userdetails.primaryEmail,
        "status": "Open"
    })

    auth_token = refresh_auth_token()

    if not auth_token:
        return "Failed to generate access token"

    headers = {
        'orgId': '60023043070',
        'Authorization': f'Zoho-oauthtoken {auth_token}',
        'Content-Type': 'application/json'
    }

    response = requests.request("POST", ZOHO_URI,
                                headers=headers,
                                data=payload,
                                timeout=REQUEST_TIMEOUT)

    if response and response.status_code == 200:
        return f"Support Ticket is generated for you. Details : {payload}"

    return "Unable to create support ticket, please try again later."
