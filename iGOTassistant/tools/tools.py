"""
This module contains the tools for the Karmayogi Bharat chatbot.
"""
import re
import sys
import os
import json
import datetime
import uuid
import logging

import time
from pathlib import Path
import requests
from dotenv import load_dotenv
# from llama_index.embeddings.huggingface import HuggingFaceEmbedding
# from llama_index.core import Settings

from iGOTassistant.utils.course_enrolment_cleanup import clean_course_enrollment_data, fetch_enrollment_data_from_api
from iGOTassistant.utils.event_enrolment_cleanup import clean_event_enrollment_data, fetch_event_enrollment_data_from_api
from iGOTassistant.utils.userDetails import UserDetailsResponse, UserDetailsService, course_enrollments_summary, create_combined_enrollment_summary, event_enrollments_summary, get_user_details

from ..models.userdetails import Userdetails
from google.adk.tools import ToolContext

# from ..utils.utils import load_documents, save_tickets, content_search_api
from ..utils.utils import (load_documents,
                           save_tickets,
                           content_search_api,
                           send_mail_api,
                           raise_ticket_mail)
from ..utils.combined_user_service import get_combined_user_details, CombinedUserDetailsContext
from ..config.config import API_ENDPOINTS, REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

load_dotenv()
KB_AUTH_TOKEN = os.getenv("KB_AUTH_TOKEN")

# Ollama configuration
OLLAMA_HOST = os.getenv('OLLAMA_HOST', 'localhost')
OLLAMA_PORT = os.getenv('OLLAMA_PORT', '11435')
# OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'llama3.2')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'ollama/llama3.1')
OLLAMA_BASE_URL = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}"

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
    print("URL for profile details: ", url)

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


# tool for changing/updating the user phone number
# def update_phone_number_tool(newphone: str, otp_auth: bool, user_id: str):
def update_phone_number_tool(newphone: str, tool_context: ToolContext):
    """
    This tool is to update or change the phone number of the user.
    This tool uses OTP verification to ensure the user is authenticated.

    Args:
        newphone: The new phone number to be updated.
    Returns:
        A string indicating the result of the operation.
    """


    # if not otp_auth:
    # if tool_context.state.get("otp_auth", False):
    #     return "Please verify your OTP before updating the phone number."

    url = API_ENDPOINTS['UPDATE']

    profile_details = read_userdetails(tool_context.state.get("user_id", None))
    user_id = tool_context.state.get("user_id", None)
    if not profile_details:
        return "Unable to fetch the user detaills, please try again later."
    profile_details["personalDetails"]["mobile"] = newphone

    payload = json.dumps({
        "request": {
            "userId": user_id,
            "phone": newphone,
            "profileDetails": profile_details
    }
    })
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {KB_AUTH_TOKEN}',
    }

    response = requests.request("PATCH", url, headers=headers, data=payload,
                                timeout=REQUEST_TIMEOUT)
    print("User ID", user_id, "profile_details", profile_details)
    print("RESPONSE at the update mobile number ", response.text)

    if response.status_code == 200: # and response.json()["params"]["status"] == "SUCCESS":
        return "Phone number updated successfully."

    return "Unable to update phone number, please try again later."




# tool function to send otp to mail/phone
def send_otp(phone: str):
    """
    This tool sends an OTP to the user's email or phone number.
    It is used for user authentication and verification.
    """
    logging.info('tool_call: send_opt')
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
    if response.status_code == 200 and response.json()["params"]["status"] == "SUCCESS":
        return "OTP sent successfully to your phone number: " + phone

    return "Unable to send OTP, please try again later." + response.json()


# tool function to verify otp
def verify_otp(phone: str, code: str):
    """
    This tool verifies the otp
    """
    url = API_ENDPOINTS['OTP']

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

    if response.status_code == 200 and response.json()["params"]["status"] == "SUCCESS":
        return "OTP verification is sucessful."

    return "Couldn't verify the OTP at the moment."


def initialize_environment():
    """
    Initialize the environment by loading the .env file and setting up global variables.
    This function should be called at the start of the application.
    """
    # Load environment variables from .env file
    load_dotenv()

    # Check required environment variables
    required_vars = ['KB_AUTH_TOKEN', 'KB_DIR']
    missing_vars = [var for var in required_vars if os.getenv(var) is None]

    if missing_vars:
        raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

    logging.info("Environment variables loaded successfully.")

def initialize_knowledge_base():
    """
    Initialize the knowledge base by loading documents from the specified directory.
    This function should be called at the start of the application.
    """
    # Load documents from the specified directory
    kb_dir = os.getenv("KB_DIR")
    kb_path = Path(kb_dir)
    if not kb_path.exists() and not kb_path.is_dir():
        raise ValueError(f"Knowledge base directory does not exist: {kb_path}")

    documents = list(kb_path.glob('**/*.*'))

    if not documents:
        raise ValueError(f"No documents found in the knowledge base directory: {kb_path}")

    return kb_dir


def initialize_embedding_model():
    """
    Initialize the embedding model by loading the specified model.
    """
    try:
        Settings.embed_model = HuggingFaceEmbedding("sentence-transformers/all-MiniLM-L6-v2")
        Settings.llm = None
    except (ImportError, ValueError, RuntimeError) as e:
        raise ValueError(f"Failed to initialize embedding model: {e}") from e
        # sys.exit(1)
    logging.info("Embedding model initialized successfully.")

# try:
#     initialize_environment()
#     KB_AUTH_TOKEN = os.getenv('KB_AUTH_TOKEN')
#     KB_DIR = initialize_knowledge_base()
#     initialize_embedding_model()

#     # Load documents using the load_documents function
#     queryengine = load_documents(KB_DIR)

#     # checking sample query
#     resp = queryengine.query("What is Karmayogi Bharat?")
#     logger.info('sample response %s', resp)
#     logging.info("Knowledge base initialized successfully.")
#     # return queryengine
# except (ValueError, FileNotFoundError, ImportError, RuntimeError) as e:
#     logging.info(f"Error initializing knowledge base: {e}")
#     sys.exit(1)

# logging.info("✅ Successfully initialized tools and knowledge base")


def create_support_ticket_tool(otp_auth: bool, userid: str, reason: str, username: str,
                               user_email: str, description: str):
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
        otp_auth: A boolean indicating whether the user is authenticated.
        reason: The user's input string.
        username: The name of the user, retrieved from the user profile.
        user_email: The email address to send the support email from.
            Provide email address without hiding here, no ** in mail
            since it is necessary to identify and revert the solution to mail id.
        description : last 5 messages of the conversation, which will be used to create the ticket.
        ** make sure that description has last five message exchanges.
        ** don't ask user for the five messages, just pass them from conversation history

    Returns:
        A string indicating the result of the operation.
    """

    if not otp_auth:
        return "You need to authenticate first before creating a support ticket."
    # tickets = load_tickets()

    # ticket_id = user_email
    ticket_id = str(uuid.uuid4())
    timestamp = datetime.datetime.now().isoformat()

    ticket_data = {
        "ticket_id" : ticket_id,
        "timestamp" : timestamp,
        "status" : "open",
        "priority" : "medium",
        "username" : username,
        "email" : user_email,
        "title" : reason,
        "description" : description 
    }

    response = raise_ticket_mail(userid, ticket_data)

    if response:
        return f"Support Ticket is generated for you. Details : {ticket_data}"

    if save_tickets(ticket_data):
        return "Support ticket has been created with following details"+\
            f" {ticket_data}. Please wait for support team to revert."

    return "Unable to create support ticket, please try again later."


def load_details_for_registered_users(otp_auth: bool, is_registered: bool, user_id : str):
    """
    Once users email address is validated, we load the other details,
    so that we can answer related questions.

    Args:
        otp_auth: A boolean indicating whether the user is authenticated.
        is_registered: this is check if validate_email function is called and user is validated.
        user_id: it is fetched from the previous validate_email function call json output. 
    """

    if not is_registered:
        return "You are not registered with Karmayogi Bharat. "\
            "We can't help you with registered account but you can still ask general questions."
    if not otp_auth:
        return "You need to authenticate first before checking the details."

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

        return [ ("system", "remember following json details for future response "\
                  + str(response.json())),
                ("assistant", "Found your details, you can ask questions now.")]

    except requests.exceptions.RequestException as e:
        logging.info(f"Error during API request: {e}")
        return "Unable to fetch user details, please try again later."


def validate_user(email : str = None, phone: str = None):
    """
    This tool validate if the email is registered with Karmayogi bharat portal or not.

    Args:
        email: email provided by user to validate if user is registered or not
        phone: phone number provided by user to validate if user is registered or not
    """
    logging.info('tool_call : validate_user %s %s', email, phone)
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

    if response.status_code != 200:
        logging.info(f"Error: {response.status_code} - {response.text}")
        return "Unable to validate email, please try again later."

    if not response.json()["result"]["response"]["content"]:
        return f'User is not registered with {identifier} you mentioned.'

    if response.status_code == 200 and response.json()["params"]["status"] == "SUCCESS":
        return [("system", "remember following json details for future response "\
                 + str(response.json())),
                 "assistant", "Found user, please wait till we fetch the details."]
    return f"{identifier} is not registered. \
     We can't help you with registerd account but you can still ask general questions."


def answer_general_questions(userquestion: str):
    """
    This tool help answer the general questions user might have,
    this help can answer the question based knowledge base provided.

    Args:
        userquestion: This argument is question user has asked. This argument can't be empty.
    """
    try:
        # global queryengine
        response = queryengine.query(userquestion)
        return str(response)
    except (AttributeError, TypeError, ValueError) as e:
        logging.info('Unable to answer the question due to a specific error: %s', str(e))
        return "Unable to answer right now, please try again later."

    return str(response)


def handle_certificate_issues(otp_auth: bool, coursename: str, user_id : str):
    """
    This tool help user figure out issued certificate after completion of course enrolled.
    This tool is only invoked/called for registered uses, and after validating user.
    Use this tool only if user is enrolled in the course mentioned, 
    otherwise provide appropriate message and dissmiss the request.

    Args:
        otp_auth: A boolean indicating whether the user is authenticated.
        coursename: for which course user want to validate against.
        user_id: This argument is user id of user who wants to get the certification 
        details of his enrolled courses. Make sure to pass right user id, 
        don't pass email id instead
    """

    if not otp_auth:
        return "You need to authenticate first before checking the certificate status."

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
        response = requests.get(url, headers=headers, timeout=60)
        if response.status_code != 200:
            return "Unable to fetch user details, please try again later."
        # Uncomment the next line to raise an exception for bad status codes
        # response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)

        # res = response.json()

        courses = response.json().get("result", {}).get("courses", [])

        targetcourse = None
        for course in courses:
            if course.get("courseName").lower() == coursename.lower():
                targetcourse = course
                break

        completion_percentage = targetcourse.get("completionPercentage")
        issued_certificate = targetcourse.get("issuedCertificate")
        content_status = targetcourse.get("contentStatus", {})
        batchid = targetcourse.get("batchId")
        logging.info(batchid)

        if completion_percentage == 100 and not issued_certificate:
            # NOTE: following code is not tested, please test before using
            logging.info("Trying send a mail")
            response = send_mail_api(user_id=user_id, coursename=targetcourse.get("courseName"))
            return "Issuing certificate " + response

        pending_content_ids = [
            content_id for content_id, status in content_status.items()
            if status != 2
        ]

        if pending_content_ids:
            pending_content_names = []
            content_details = content_search_api(pending_content_ids)
            # pending_content_names.append(content_details.get("name", "Unknown"))
            pending_content_names = content_details

            return "You seem to have not completed the course components." \
            "Following contents are still pending and in progress" \
            + ", ".join(pending_content_names)
        return "You haven't finished the course components."
    except requests.exceptions.RequestException as e:
        logging.info(f"Error during API request: {e}")
        return "Unable to fetch user details, please try again later."


def list_pending_contents(otp_auth: bool, coursename: str, user_id: str):
    """
    Use this tool when user ask which contents are pending from course XYZ.
    Fetches content details from the Karmayogi Bharat API.
    Args:
        otp_auth (bool): A boolean indicating whether the user is authenticated.
        coursename (str): The name of the course to check for pending contents.
        user_id (str): The ID of the user to check for pending contents.
    Returns:
        dict|str: A dictionary containing the content details.
    """
    if not otp_auth:
        return "You need to authenticate first before checking the pending contents."

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
        response = requests.get(url, headers=headers, timeout=60)
        if response.status_code != 200:
            return "Unable to fetch user details, please try again later."
        # Uncomment the next line to raise an exception for bad status codes
        # response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)

        # res = response.json()

        courses = response.json().get("result", {}).get("courses", [])

        targetcourse = None
        for course in courses:
            if course.get("courseName").lower() == coursename.lower():
                targetcourse = course
                break

        # completion_percentage = targetcourse.get("completionPercentage")
        # issued_certificate = targetcourse.get("issuedCertificate")
        content_status = targetcourse.get("contentStatus", {})


        pending_content_ids = [
            content_id for content_id, status in content_status.items()
            if status != 2
        ]

        if pending_content_ids:
            pending_content_names = []
            content_details = content_search_api(pending_content_ids)
            # pending_content_names.append(content_details.get("name", "Unknown"))
            pending_content_names = content_details

            return "You seem to have not completed the course components." \
            "Following contents are still pending and in progress" \
            + ", ".join(pending_content_names)
        return "You haven't finished the course components."
    except requests.exceptions.RequestException as e:
        logging.info(f"Error during API request: {e}")
        return "Unable to fetch user details, please try again later."
    except Exception as e:
        # return {identifier : None for identifier in content_id}
        return "Unable to load pending contents"


async def get_combined_user_details_tool(tool_context: ToolContext, force_refresh: bool = False):
    """
    This tool combines fetch_userdetails and load_details_for_registered_users functionality
    into a single operation and stores the result in Redis for efficient access.
    
    This tool fetches both user profile information and enrollment details in one call,
    caches the combined data in Redis, and provides a unified interface for accessing
    user information.
    
    Args:
        tool_context: ToolContext object containing user_id and other state information
        force_refresh: If True, forces a fresh fetch from the API even if cached data exists
        
    Returns:
        A tuple containing system message with user details and assistant confirmation message
    """
    try:
        user_id = tool_context.state.get("user_id")
        
        if not user_id:
            return "Unable to load user ID, please try again later."
        
        
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

        response = requests.get(url=url, headers=headers)
        resp_json = response.json()
        print(resp_json)
        user_details = resp_json.get("result", {}).get("response", {}) # .get("content", [])
        if not (response.status_code == 200 and resp_json["params"]["status"] == "SUCCESS") or not user_details:
            return f"{identifier} is not registered. \\n        We can't help you with registerd account but you can still ask general questions."


        # Create user object
        user = Userdetails()
        user.userId = user_details.get("userId", "")
        user.firstName = user_details.get("firstName", "")
        user.lastName = user_details.get("lastName", "")
        user.primaryEmail = user_details.get("profileDetails", {}).get("personalDetails", {}).get("primaryEmail", "")
        user.phone = user_details.get("profileDetails", {}).get("personalDetails", {}).get("mobile", "")

        # Store basic user details in state
        tool_context.state['validuser'] = True
        tool_context.state['userdetails'] = dict(user)
        tool_context.state['loaded_details'] = True

        
        url = f"{API_ENDPOINTS['ENROLL']}/{user_id}"
        print("URL", url)

        headers = {
            "Accept" : "application/json",
            "Content-Type" : "application/json",
            "Authorization" : f"Bearer {KB_AUTH_TOKEN}"
        }

        try:
            # actual_user_id = tool_context.state.get("user_id")
            user_course_enrollment_info, course_enrollments = await UserDetailsService()._fetch_course_enrollments(user_id=user_id)
            print("USER_COURSE_ENROLLMENT_INFO", user_course_enrollment_info, "COURSE_ENROLLMENT", course_enrollments)
            event_enrollments = await UserDetailsService()._fetch_event_enrollments(user_id=user_id)
            print("EVENT_ENROLLMENT", event_enrollments)

            # Defensive: Ensure course_enrollments and event_enrollments are lists
            if not isinstance(course_enrollments, list):
                logger.info(f"Expected list for course_enrollments, got {type(course_enrollments)}: {course_enrollments}")
                course_enrollments = []
            if not isinstance(event_enrollments, list):
                logger.info(f"Expected list for event_enrollments, got {type(event_enrollments)}: {event_enrollments}")
                event_enrollments = []

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

            user.karmaPoints = user_course_enrollment_info.get("karmaPoints", 0)

            # Create unified JSON object combining user, enrollment summary, and course enrollments
            unified_user_data = {
                "user_details": {
                    "userId": user.userId,
                    "firstName": user.firstName,
                    "lastName": user.lastName,
                    "primaryEmail": user.primaryEmail,
                    "phone": user.phone,
                    # "karmaPoints": user_course_enrollment_info.get("karmaPoints", 0),
                    "karmaPoints": user.karmaPoints,
                },
                "combined_enrollment_summary": combined_enrollment_summary,
                "course_enrollments": updated_course_enrollments,
                "event_enrollments": updated_event_enrollments,
                "metadata": {
                    "total_courses": len(updated_course_enrollments),
                    "total_events": len(updated_event_enrollments),
                    "total_enrollments": len(updated_course_enrollments) + len(updated_event_enrollments),
                    "timestamp": time.time(),
                    "user_id": user_id
                }
            }

            # Store the unified data in Redis and tool context
            try:
                from ..utils.combined_user_service import combined_user_service
                cache_key = combined_user_service._generate_cache_key(user_id)
                ttl_seconds = combined_user_service.default_ttl * 60
                
                # Store in Redis
                redis_client = await combined_user_service._get_redis()
                await redis_client.set(cache_key, json.dumps(unified_user_data), ex=ttl_seconds)
                
                # Store in tool context
                tool_context.state['combined_user_details'] = unified_user_data
                tool_context.state['user_summary'] = {
                    "user_id": user.userId,
                    "first_name": user.firstName,
                    "last_name": user.lastName,
                    "course_count": len(updated_course_enrollments),
                    "event_count": len(updated_event_enrollments),
                    "total_enrollments": len(updated_course_enrollments) + len(updated_event_enrollments),
                    "last_updated": time.time()
                }
                
                logger.info(f"Stored unified user data in Redis and state for user: {user_id}")
                
            except Exception as e:
                logger.error(f"Failed to store unified user data: {e}")

            # return [("system", "remember following json details for future response " + json.dumps(unified_user_data, indent=2)),
            return [("system", "remember following json details for future response " + json.dumps(user.to_json(), indent=2)),
                    ("assistant", "Found your details, you can ask questions now.")]

        except requests.exceptions.RequestException as e:
            logger.info("Error during API request: %s", e)
            return "Unable to fetch user details, please try again later."
            
        # Store the combined details in tool context for other tools to use
        # # # tool_context.state['combined_user_details'] = combined_details.to_dict()
        # # # tool_context.state['user_summary'] = combined_details.to_summary()
        # # # tool_context.state['validuser'] = True
        # # # tool_context.state['loaded_details'] = True
        
        # # # Create context string for LLM
        # # context_string = combined_details.get_full_context()
        
        # cache_status = "from cache" if was_cached else "freshly fetched"
        
        # return [
        #     ("system", f"remember following combined user details ({cache_status}): {context_string}"),
        #     ("assistant", f"Found your complete details ({cache_status}), you can now ask questions about your courses, events, and profile information.")
        # ]
        
    except Exception as e:
        logger.error(f"Error in get_combined_user_details_tool: {e}")
        return f"Unable to fetch user details, please try again later. Error: {str(e)}"


async def get_user_summary_tool(tool_context: ToolContext):
    """
    This tool provides a lightweight summary of user details without loading full data.
    Useful for quick checks and reducing token usage in LLM context.
    
    Args:
        tool_context: ToolContext object containing user_id and other state information
        
    Returns:
        A summary string of user information
    """
    try:
        user_id = tool_context.state.get("user_id")
        
        if not user_id:
            return "User ID not available."
        
        # Check if we have unified data in state first
        unified_data = tool_context.state.get("combined_user_details")
        if unified_data:
            user_details = unified_data.get("user_details", {})
            metadata = unified_data.get("metadata", {})
            return f"User {user_details.get('firstName', '')} {user_details.get('lastName', '')} has {metadata.get('total_courses', 0)} courses and {metadata.get('total_events', 0)} events enrolled."
        
        # Fallback to cache
        from ..utils.combined_user_service import get_combined_user_summary
        summary = await get_combined_user_summary(user_id)
        
        if summary:
            return f"User {summary['first_name']} {summary['last_name']} has {summary['course_count']} courses and {summary['event_count']} events enrolled. Last updated: {summary['last_updated']}"
        else:
            return "User summary not available in cache. Please use get_combined_user_details_tool first."
            
    except Exception as e:
        logger.error(f"Error in get_user_summary_tool: {e}")
        return f"Unable to get user summary: {str(e)}"


async def initialize_session_with_user_details(tool_context: ToolContext):
    """
    This tool automatically fetches and initializes combined user details whenever a session starts.
    It should be called at the beginning of each conversation to ensure user data is always available.
    
    This tool:
    1. Fetches combined user details (profile + enrollments)
    2. Stores data in session state for other tools to use
    3. Provides a welcome message with user context
    4. Handles errors gracefully with appropriate fallbacks
    
    Args:
        tool_context: ToolContext object containing user_id, cookie, and session state
        
    Returns:
        A tuple containing system message with user details and personalized welcome message
    """
    try:
        user_id = tool_context.state.get("user_id")
        
        if not user_id:
            return [
                ("system", "User ID not available. User may need to authenticate first."),
                ("assistant", "I'm here to help you with Karmayogi Bharat! Please provide your user ID to get started.")
            ]
        
        
        
        # Check if we already have user details in session (avoid duplicate calls)
        if tool_context.state.get("combined_user_details") and tool_context.state.get("session_initialized"):
            # User details already loaded, just provide a welcome back message
            unified_data = tool_context.state.get("combined_user_details", {})
            user_details = unified_data.get("user_details", {})
            metadata = unified_data.get("metadata", {})
            if user_details:
                return [
                    ("system", f"Session already initialized with user details: {user_details.get('firstName', '')} {user_details.get('lastName', '')}"),
                    ("assistant", f"Welcome back! I have your information ready. You have {metadata.get('total_courses', 0)} courses and {metadata.get('total_events', 0)} events enrolled. How can I help you today?")
                ]
        
        # Get combined user details from cache or fetch fresh
        logger.info(f"Initializing session with user details for user: {user_id}")
        combined_details, was_cached = await get_combined_user_details(user_id, cookie, force_refresh=False)
        
        # Store the combined details in tool context for other tools to use
        tool_context.state['combined_user_details'] = combined_details.to_dict()
        tool_context.state['user_summary'] = combined_details.to_summary()
        tool_context.state['validuser'] = True
        tool_context.state['loaded_details'] = True
        tool_context.state['session_initialized'] = True
        tool_context.state['session_init_timestamp'] = time.time()
        
        # Create personalized welcome message
        welcome_message = _create_personalized_welcome_message(combined_details)
        
        # Create context string for LLM (truncated for efficiency)
        context_summary = _create_context_summary(combined_details)
        
        cache_status = "from cache" if was_cached else "freshly fetched"
        
        return [
            ("system", f"Session initialized with combined user details ({cache_status}): {context_summary}"),
            ("assistant", welcome_message)
        ]
        
    except Exception as e:
        logger.error(f"Error in initialize_session_with_user_details: {e}")
        
        # Provide fallback welcome message
        return [
            ("system", f"Session initialization failed: {str(e)}. User may need to re-authenticate."),
            ("assistant", "Welcome to Karmayogi Bharat! I'm having trouble loading your information right now. You can still ask general questions, or try refreshing your session.")
        ]


def _create_personalized_welcome_message(unified_data: dict) -> str:
    """
    Create a personalized welcome message based on unified user data.
    
    Args:
        unified_data: Dictionary containing user details, enrollment summary, and course enrollments
        
    Returns:
        Personalized welcome message string
    """
    try:
        user_details = unified_data.get("user_details", {})
        metadata = unified_data.get("metadata", {})
        
        first_name = user_details.get("firstName", "there")
        course_count = metadata.get("total_courses", 0)
        event_count = metadata.get("total_events", 0)
        total_enrollments = metadata.get("total_enrollments", 0)
        
        # Base welcome message
        welcome = f"Hello {first_name}! Welcome to Karmayogi Bharat. "
        
        # Add enrollment information
        if total_enrollments > 0:
            if course_count > 0 and event_count > 0:
                welcome += f"I can see you're enrolled in {course_count} courses and {event_count} events. "
            elif course_count > 0:
                welcome += f"I can see you're enrolled in {course_count} courses. "
            elif event_count > 0:
                welcome += f"I can see you're enrolled in {event_count} events. "
            
            welcome += "I'm here to help you with any questions about your learning journey, course progress, certificates, or any other Karmayogi Bharat related queries."
        else:
            welcome += "I'm here to help you with any questions about Karmayogi Bharat, course enrollments, or learning opportunities."
        
        return welcome
        
    except Exception as e:
        logger.error(f"Error creating personalized welcome message: {e}")
        return "Hello! Welcome to Karmayogi Bharat. I'm here to help you with any questions about your learning journey."


def _create_context_summary(unified_data: dict) -> str:
    """
    Create a concise context summary for LLM usage.
    
    Args:
        unified_data: Dictionary containing user details, enrollment summary, and course enrollments
        
    Returns:
        Concise context summary string
    """
    try:
        user_details = unified_data.get("user_details", {})
        metadata = unified_data.get("metadata", {})
        combined_enrollment_summary = unified_data.get("combined_enrollment_summary", {})
        
        summary_parts = [
            f"User: {user_details.get('firstName', '')} {user_details.get('lastName', '')}",
            f"Email: {user_details.get('primaryEmail', '')}",
            f"Enrollments: {metadata.get('total_courses', 0)} courses, {metadata.get('total_events', 0)} events",
            f"Total: {metadata.get('total_enrollments', 0)} enrollments",
            f"Status: Authenticated"
        ]
        
        # Add enrollment summary if available
        if combined_enrollment_summary:
            if combined_enrollment_summary.get("courses"):
                course_summary = combined_enrollment_summary["courses"]
                summary_parts.append(f"Course Summary: {course_summary.get('total_courses', 0)} total, {course_summary.get('completed_courses', 0)} completed")
            
            if combined_enrollment_summary.get("events"):
                event_summary = combined_enrollment_summary["events"]
                summary_parts.append(f"Event Summary: {event_summary.get('total_events', 0)} total, {event_summary.get('completed_events', 0)} completed")
        
        return " | ".join(summary_parts)
        
    except Exception as e:
        logger.error(f"Error creating context summary: {e}")
        return f"User: {metadata.get('user_id', 'Unknown')} | Enrollments: {metadata.get('total_enrollments', 0)}"


async def refresh_user_details_tool(tool_context: ToolContext):
    """
    This tool refreshes user details by forcing a fresh fetch from the API.
    Useful when user data might be stale or when user has made recent changes.
    
    Args:
        tool_context: ToolContext object containing user_id and cookie
        
    Returns:
        Confirmation message about the refresh operation
    """
    try:
        user_id = tool_context.state.get("user_id")
        
        if not user_id:
            return "Unable to refresh user details. User ID or cookie not available."
        
        # Force refresh by setting force_refresh=True
        logger.info(f"Refreshing user details for user: {user_id}")
        combined_details, was_cached = await get_combined_user_details(user_id, force_refresh=True)
        
        # Update session state
        tool_context.state['combined_user_details'] = combined_details.to_dict()
        tool_context.state['user_summary'] = combined_details.to_summary()
        tool_context.state['last_refresh_timestamp'] = time.time()
        
        return f"User details refreshed successfully! You have {combined_details.course_count} courses and {combined_details.event_count} events enrolled. Your information is now up to date."
        
    except Exception as e:
        logger.error(f"Error in refresh_user_details_tool: {e}")
        return f"Unable to refresh user details: {str(e)}"


async def get_session_status_tool(tool_context: ToolContext):
    """
    This tool provides information about the current session status and user data availability.
    
    Args:
        tool_context: ToolContext object containing session state
        
    Returns:
        Session status information
    """
    try:
        user_id = tool_context.state.get("user_id")
        session_initialized = tool_context.state.get("session_initialized", False)
        user_summary = tool_context.state.get("user_summary", {})
        
        status_parts = [f"User ID: {user_id or 'Not set'}"]
        
        if session_initialized:
            status_parts.append("Session: Initialized")
            if user_summary:
                status_parts.append(f"User: {user_summary.get('first_name', 'Unknown')} {user_summary.get('last_name', '')}")
                status_parts.append(f"Enrollments: {user_summary.get('course_count', 0)} courses, {user_summary.get('event_count', 0)} events")
                
                # Add cache age information
                last_updated = user_summary.get('last_updated', 'Unknown')
                status_parts.append(f"Last Updated: {last_updated}")
        else:
            status_parts.append("Session: Not initialized")
            status_parts.append("User details not loaded")
        
        return " | ".join(status_parts)
        
    except Exception as e:
        logger.error(f"Error in get_session_status_tool: {e}")
        return f"Unable to get session status: {str(e)}"


async def answer_course_event_questions(tool_context: ToolContext, question: str):
    """
    This tool uses the combined user details from Redis or state to answer questions
    about courses and events. It leverages the LLM to provide context-aware responses.
    
    Args:
        tool_context: ToolContext object containing user_id and other state information
        question: The user's question about courses or events.
        
    Returns:
        A string containing the LLM's response to the question.
    """
    try:
        user_id = tool_context.state.get("user_id")
        
        if not user_id:
            return "User ID not available to answer course/event questions."
        
        # Get combined user details from Redis or state
        unified_data = tool_context.state.get("combined_user_details")
        if not unified_data:
            return "User details not loaded. Please use get_combined_user_details_tool first."
        
        # Extract relevant information for the LLM prompt
        user_details = unified_data.get("user_details", {})
        course_enrollments = unified_data.get("course_enrollments", [])
        event_enrollments = unified_data.get("event_enrollments", [])
        
        # Construct a prompt for the LLM
        prompt_template = """
        You are a helpful assistant that can answer questions about Karmayogi Bharat courses and events.
        You have access to the following user details:
        - User ID: {user_id}
        - First Name: {first_name}
        - Last Name: {last_name}
        - Primary Email: {primary_email}
        - Phone: {phone}

        You also have access to the following course enrollments:
        {course_enrollments_str}

        You also have access to the following event enrollments:
        {event_enrollments_str}

        Question: {question}
        Answer:
        """
        
        course_enrollments_str = "\n".join([
            f"- Course: {ce.get('courseName', 'N/A')}, Status: {ce.get('status', 'N/A')}, Progress: {ce.get('completionPercentage', 'N/A')}%"
            for ce in course_enrollments
        ])
        
        event_enrollments_str = "\n".join([
            f"- Event: {ee.get('eventName', 'N/A')}, Status: {ee.get('status', 'N/A')}, Progress: {ee.get('completionPercentage', 'N/A')}%"
            for ee in event_enrollments
        ])
        
        prompt = prompt_template.format(
            user_id=user_id,
            first_name=user_details.get("firstName", "there"),
            last_name=user_details.get("lastName", "there"),
            primary_email=user_details.get("primaryEmail", "N/A"),
            phone=user_details.get("phone", "N/A"),
            course_enrollments_str=course_enrollments_str,
            event_enrollments_str=event_enrollments_str,
            question=question
        )
        
        # Use Ollama to generate the response
        ollama_url = f"{OLLAMA_BASE_URL}/api/generate"
        headers = {"Content-Type": "application/json"}
        data = {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False
        }
        
        response = requests.post(ollama_url, headers=headers, json=data, timeout=REQUEST_TIMEOUT)
        
        if response.status_code == 200:
            result = response.json()
            return result["response"]
        else:
            error_msg = f"Failed to get response from Ollama: {response.status_code} - {response.text}"
            logger.error(error_msg)
            return error_msg
            
    except Exception as e:
        logger.error(f"Error in answer_course_event_questions: {e}")
        return f"Unable to answer course/event question: {str(e)}"
