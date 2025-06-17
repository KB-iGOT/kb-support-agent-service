"""
This file is used for newly added session based tools,
which authenticate the user from session inside tools.

"""


import logging
import os
import json
import re
import requests
from dotenv import load_dotenv

from google.adk.tools import ToolContext

from ..models.userdetails import Userdetails
from ..config.config import API_ENDPOINTS, REQUEST_TIMEOUT

logger = logging.getLogger(__name__)
load_dotenv()
KB_AUTH_TOKEN = os.getenv("KB_AUTH_TOKEN")


def validate_user(tool_context: ToolContext, email: str = "", phone: str = ""):
    """
    This tool validate if the email is registered with Karmayogi bharat portal or not.
    user can provide either phone number or email address.

    Args:
        email: email provided by user to validate if user is registered or not
        phone: phone number provided by user to validate if user is registered or not
    """
    if not email and not phone:
        return "Please provide either email or phone number to validate."

    url = API_ENDPOINTS['USER_SEARCH']
    headers = {
        "Accept" : "application/json",
        "Content-Type" : "application/json",
        "Authorization" : f"Bearer {KB_AUTH_TOKEN}"
    }

    filters = {}
    identifier = email if email else phone

    if email:
        email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_regex, email):
            return ValueError('Email format is not valid')

        filters["email"] = email
    else:
        filters["phone"] = phone

    data = {
        "request" : {
            "filters" : filters,
            "limit" : 1
        }
    }

    response = requests.post(url=url, headers=headers, json=data, timeout=REQUEST_TIMEOUT)

    if not response.status_code == 200 and not response.json()["params"]["status"] == "SUCCESS":
        return f"{identifier} is not registered. \
        We can't help you with registerd account but you can still ask general questions."

    user_details = response.json().get("result", {}).get("response", {}).get("content", [])[0]

    if not user_details:
        return { "message" : "Failed to extract user details."}

    user = Userdetails()
    user.userId = user_details.get("userId", "")
    user.firstName = user_details.get("firstName", "")
    user.lastName = user_details.get("lastName", "")
    user.primaryEmail = user_details.get("profileDetails", {}).get("personalDetails", {})["primaryEmail"]
    user.phone = user_details.get("profileDetails", {}).get("personalDetails", {})["mobile"]

    tool_context.state['validuser'] = True
    # tool_context.state['userdetails'] = user.to_json()
    tool_context.state['userdetails'] = dict(user)

    return [("system","remember following json details for future response " + str(user.to_json())),
            "assistant", "Found user, You can proceed with OTP authentication "]


def load_details_for_registered_users(tool_context: ToolContext, user_id : str):
    """
    Once users email address is validated, we load the other details,
    so that we can answer related questions.

    Args:
        user_id: it is fetched from the previous validate_email function call json output. 
    """
    if tool_context.state.get('validuser', False) and not tool_context.state.get('otp_auth', False):
        return "You need to authenticate the user first"


    url = f"{API_ENDPOINTS['ENROLL']}/{user_id}"\
        "?licenseDetails=name,description,url&fields=contentType,topic,name,"\
        "channel&batchDetails=name,endDate,startDate,status,enrollmentType,"\
        "createdBy,certificates"

    headers = {
        "Accept" : "application/json",
        "Content-Type" : "application/json",
        "Authorization" : f"Bearer {KB_AUTH_TOKEN}"
    }

    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        if response.status_code != 200:
            return "Unable to fetch user details, please try again later."
        # Uncomment the next line to raise an exception for bad status codes
        # response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)

        userdata = response.json()

        for course in userdata["result"]["courses"]:
            if 'content' in course:
                del course['content']
            if 'batch' in course:
                del course['batch']

        tool_context.state['userprofile'] = userdata


        return [ ("system", "remember following json details for future response "\
                  + str(userdata)),
                ("assistant", "Found your details, you can ask questions now.")]

    except requests.exceptions.RequestException as e:
        logging.info("Error during API request: %s", e)
        return "Unable to fetch user details, please try again later."


def read_userdetails(user_id: str):
    """
    This function reads the user details from the Karmayogi Bharat API.
    It is used to fetch the personal details of the user.
    Args:
        user_id: The ID of the user whose details are to be fetched.
    Returns:
        A dictionary containing the user's personal details.
    """
    url = API_ENDPOINTS['PROFILE'] + user_id

    payload = {}
    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {KB_AUTH_TOKEN}'
    }

    response = requests.request("GET", url, headers=headers, data=payload, timeout=REQUEST_TIMEOUT)

    profile_details = None
    if response.status_code == 200 and response.json()["params"]["status"] == "SUCCESS":
        profile_details = response.json()["result"]["response"]["profileDetails"]

    return profile_details


def update_name(tool_context: ToolContext, user_id: str, newname: str):
    """
    This tool is to update or change the phone number of the user.
    This tool uses OTP verification to ensure the user is authenticated.

    Args:
        user_id: The ID of the user whose name is to be updated.
        newname: The new name to be updated.
    Returns:
        A string indicating the result of the operation.
    """

    if not tool_context.state.get('otp_auth', False):
        return "You need to authenticate the user first"

    url = API_ENDPOINTS['UPDATE']

    profile_details = read_userdetails(user_id)
    if not profile_details:
        return "Unable to fetch the user detaills, please try again later."

    profile_details["personalDetails"]["firstname"] = newname

    payload = json.dumps({
        "request": {
            "userId": user_id,
            "firstname": newname,
            "profileDetails": profile_details
    }
    })
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {KB_AUTH_TOKEN}',
    }

    response = requests.request("PATCH", url, headers=headers, data=payload,
                                timeout=REQUEST_TIMEOUT)

    if response.status_code == 200:
        return "Phone number updated successfully."

    return "Unable to update phone number, please try again later."
