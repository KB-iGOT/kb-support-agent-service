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

from iGOTassistant.utils.course_enrolment_cleanup import clean_course_enrollment_data, fetch_enrollment_data_from_api
from iGOTassistant.utils.event_enrolment_cleanup import clean_event_enrollment_data, fetch_event_enrollment_data_from_api
from iGOTassistant.utils.userDetails import UserDetailsResponse, UserDetailsService, course_enrollments_summary, create_combined_enrollment_summary, event_enrollments_summary, get_user_details

from ..models.userdetails import Userdetails
from ..config.config import API_ENDPOINTS, KB_BASE_URL, REQUEST_TIMEOUT

logger = logging.getLogger(__name__)
load_dotenv()
KB_AUTH_TOKEN = os.getenv("KB_AUTH_TOKEN")






def fetch_userdetails(tool_context: ToolContext):
    """
    This tool fetches the user details from the server at the beginning of the conversation.

    Args:
        tool_context: to access the user id from the state.
    """
    user_id = tool_context.state.get("user_id", None)
    print("USER_ID", user_id)

    # if not user_id:
    #     return "Unable to load user id, please try again later."

    url = API_ENDPOINTS['PROFILE'] + user_id
    print("URL", url)
    headers = {
        "Accept" : "application/json",
        "Content-Type" : "application/json",
        "Authorization" : f"Bearer {KB_AUTH_TOKEN}"
    }

    filters = {}
    identifier = user_id
    filters["id"] = user_id
    data = {
        "request" : {
            "filters" : filters,
            "limit" : 1
        }
    }

    # response = requests.post(url=url, headers=headers, json=data, timeout=REQUEST_TIMEOUT)
    # response = requests.get(url=url, headers=headers, timeout=REQUEST_TIMEOUT)
    response = requests.get(url=url, headers=headers)
    resp_json = response.json()
    print(resp_json)
    user_details = resp_json.get("result", {}).get("response", {}) # .get("content", [])
    if not (response.status_code == 200 and resp_json["params"]["status"] == "SUCCESS") or not user_details:
        return f"{identifier} is not registered. \\n        We can't help you with registerd account but you can still ask general questions."

    # user_details = content_list[0]
    # user_details = content_list
    # if not user_details:
    #     return { "message" : "Failed to extract user details."}

    user = Userdetails()
    user.userId = user_details.get("userId", "")
    user.firstName = user_details.get("firstName", "")
    user.lastName = user_details.get("lastName", "")
    user.primaryEmail = user_details.get("profileDetails", {}).get("personalDetails", {}).get("primaryEmail", "")
    user.phone = user_details.get("profileDetails", {}).get("personalDetails", {}).get("mobile", "")

    tool_context.state['validuser'] = True
    tool_context.state['userdetails'] = dict(user)
    tool_context.state['loaded_details'] = True

    return [("system","remember following json details for future response " + user.to_json()),
            ("assistant", "Found user, You can proceed with loading registered user details.")]


def validate_user(tool_context: ToolContext, email: str , phone: str ):
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
    resp_json = response.json()
    content_list = resp_json.get("result", {}).get("response", {}).get("content", [])
    if not (response.status_code == 200 and resp_json["params"]["status"] == "SUCCESS") or not content_list:
        return f"{identifier} is not registered. \\n        We can't help you with registerd account but you can still ask general questions."

    user_details = content_list[0]
    if not user_details:
        return { "message" : "Failed to extract user details."}

    user = Userdetails()
    user.userId = user_details.get("userId", "")
    user.firstName = user_details.get("firstName", "")
    user.lastName = user_details.get("lastName", "")
    user.primaryEmail = user_details.get("profileDetails", {}).get("personalDetails", {}).get("primaryEmail", "")
    user.phone = user_details.get("profileDetails", {}).get("personalDetails", {}).get("mobile", "")

    tool_context.state['validuser'] = True
    tool_context.state['userdetails'] = dict(user)

    return [("system","remember following json details for future response " + str(user.to_json())),
            ("assistant", "Found user, You can proceed with OTP authentication ")]


async def load_details_for_registered_users(tool_context: ToolContext, user_id : str):
    """
    Once users email address is validated, we load the other details,
    so that we can answer related questions.

    Args:
        user_id: it is fetched from the previous validate_email function call json output. 
    """
    # if tool_context.state.get('validuser', False) and not tool_context.state.get('otp_auth', False):
    # if tool_context.state.get('validuser', False): # and not tool_context.state.get('otp_auth', False):
    #     return "You need to authenticate the user first"


    url = f"{API_ENDPOINTS['ENROLL']}/{user_id}"
    print("URL", url)

    headers = {
        "Accept" : "application/json",
        "Content-Type" : "application/json",
        "Authorization" : f"Bearer {KB_AUTH_TOKEN}"
    }

    try:
        # response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        # if response.status_code != 200:
        #     return "Unable to fetch user details, please try again later."
        # # Uncomment the next line to raise an exception for bad status codes
        # # response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)

        # userdata = response.json()

        # for course in userdata["result"]["courses"]:
        #     if 'content' in course:
        #         del course['content']
        #     if 'batch' in course:
        #         del course['batch']

        # tool_context.state['userprofile'] = userdata
        # userdata = ""

        # course_response = fetch_enrollment_data_from_api(user_id, KB_AUTH_TOKEN, KB_BASE_URL)
        # course_response = clean_course_enrollment_data(course_response)

        # event_response = fetch_event_enrollment_data_from_api(user_id, KB_AUTH_TOKEN, KB_BASE_URL)
        # event_response = clean_event_enrollment_data(event_response)
        # response = get_user_details(tool_context.state.get("user_id"))
        actual_user_id = tool_context.state.get("user_id")
        user_course_enrollment_info, course_enrollments = await UserDetailsService()._fetch_course_enrollments(user_id=actual_user_id)
        print("USER_COURSE_ENROLLMENT_INFO", user_course_enrollment_info, "COURSE_ENROLLMENT", course_enrollments)
        event_enrollments = await UserDetailsService()._fetch_event_enrollments(user_id=actual_user_id)
        print("EVENT_ENROLLMENT", event_enrollments)

        # Defensive: Ensure course_enrollments and event_enrollments are lists
        if not isinstance(course_enrollments, list):
            logger.info(f"Expected list for course_enrollments, got {type(course_enrollments)}: {course_enrollments}")
            course_enrollments = []
        if not isinstance(event_enrollments, list):
            logger.info(f"Expected list for event_enrollments, got {type(event_enrollments)}: {event_enrollments}")
            event_enrollments = []

        # cleaned_course_enrollments = [
        #     course for course in clean_course_enrollment_data(course_enrollments)
        #     if isinstance(course, dict)
        # ]
        cleaned_course_enrollments = clean_course_enrollment_data(course_enrollments)
        print("CLEANED_COURSES", cleaned_course_enrollments)
        cleaned_event_enrollments = [
            event for event in clean_event_enrollment_data(event_enrollments)
            if isinstance(event, dict)
        ]
        print("CLEANED_EVENT", cleaned_event_enrollments)

        # Create individual summaries
        course_summary = course_enrollments_summary(user_course_enrollment_info, cleaned_course_enrollments)
        event_summary = event_enrollments_summary(cleaned_event_enrollments)

        # Combine summaries
        combined_enrollment_summary = create_combined_enrollment_summary(course_summary, event_summary)

        # Remove all null, empty string values and empty arrays from enrollment data
        updated_course_enrollments = [
            {k: v for k, v in course.items() if v not in [None, '', [], {}]}
            for course in cleaned_course_enrollments
        ]
        updated_event_enrollments = [
            {k: v for k, v in event.items() if v not in [None, '', [], {}]}
            for event in cleaned_event_enrollments
        ]

        return [("system", "remember following json details for future response "
                + str(combined_enrollment_summary) + str(updated_course_enrollments)),
                ("assistant", "Found your details, you can ask questions now.")]

    except requests.exceptions.RequestException as e:
        logger.info("Error during API request: %s", e)
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


def update_name(tool_context: ToolContext, newname: str):
    """
    This tool is to update or change the phone number of the user.
    This tool uses OTP verification to ensure the user is authenticated.

    Args:
        newname: The new name to be updated.
    Returns:
        A string indicating the result of the operation.
    """

    if not tool_context.state.get('otp_auth', False):
        return "You need to authenticate the user first"

    url = API_ENDPOINTS['UPDATE']

    user_id = tool_context.state.get("user_id", None)

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
        return f"Your name has been updated to {newname}"

    return "Sorry, I couldn't update your name at the moment."
