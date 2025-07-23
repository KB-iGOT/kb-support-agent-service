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


from iGOTassistant.utils.course_enrolment_cleanup import clean_course_enrollment_data, fetch_enrollment_data_from_api
from iGOTassistant.utils.event_enrolment_cleanup import clean_event_enrollment_data, fetch_event_enrollment_data_from_api
from iGOTassistant.utils.userDetails import UserDetailsResponse, UserDetailsService, course_enrollments_summary, create_combined_enrollment_summary, event_enrollments_summary, get_user_details

from ..models.userdetails import Userdetails
from google.adk.tools import ToolContext


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


def update_phone_number_tool(newphone: str, tool_context: ToolContext):
    """
    This tool is to update or change the phone number of the user.
    This tool uses OTP verification to ensure the user is authenticated.

    Args:
        newphone: The new phone number to be updated.
    Returns:
        A string indicating the result of the operation.
    """
    user_id = tool_context.state.get("user_id", None)
    if not user_id:
        return "User ID not available. Please ensure user details are loaded first."
    
    # Check if user is authenticated
    if not tool_context.state.get("otp_auth", False):
        return "Please verify your OTP before updating the phone number."

    url = API_ENDPOINTS['UPDATE']

    # Get current user details
    profile_details = read_userdetails(user_id)
    if not profile_details:
        return "Unable to fetch the user details, please try again later."
    
    # Update the phone number in profile details
    if "personalDetails" not in profile_details:
        profile_details["personalDetails"] = {}
    
    profile_details["personalDetails"]["mobile"] = newphone

    payload = {
        "request": {
            "userId": user_id,
            "phone": newphone,
            "profileDetails": profile_details
        }
    }
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {KB_AUTH_TOKEN}',
    }

    # Make API call with timing
    start_time = time.time()
    try:
        response = requests.request("PATCH", url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
        response_time = time.time() - start_time
        
        # Handle response
        if response.status_code == 200:
            try:
                response_json = response.json()
                
                # Check if the API indicates success
                if response_json.get("params", {}).get("status") == "SUCCESS":
                    return "Phone number updated successfully."
                else:
                    error_msg = response_json.get("params", {}).get("errmsg", "Unknown error")
                    return f"Unable to update phone number. Error: {error_msg}"
                    
            except (ValueError, json.JSONDecodeError) as e:
                # If we can't parse JSON but status is 200, assume success
                return "Phone number updated successfully."
        else:
            error_msg = f"API returned status code {response.status_code}"
            return f"Unable to update phone number. {error_msg}"
            
    except requests.exceptions.Timeout:
        return "Unable to update phone number. Request timed out. Please try again later."
    except requests.exceptions.RequestException as e:
        return f"Unable to update phone number due to a network error: {str(e)}"
    except Exception as e:
        return f"Unable to update phone number. An unexpected error occurred: {str(e)}"


def update_email_tool(newemail: str, tool_context: ToolContext):
    """
    This tool is to update or change the email address of the user.
    This tool uses OTP verification to ensure the user is authenticated.

    Args:
        newemail: The new email address to be updated.
    Returns:
        A string indicating the result of the operation.
    """
    user_id = tool_context.state.get("user_id", None)
    if not user_id:
        return "User ID not available. Please ensure user details are loaded first."
    
    # Check if user is authenticated
    if not tool_context.state.get("otp_auth", False):
        return "Please verify your OTP before updating the email address."

    url = API_ENDPOINTS['UPDATE']

    # Get current user details
    profile_details = read_userdetails(user_id)
    if not profile_details:
        return "Unable to fetch the user details, please try again later."
    
    # Update the email in profile details
    if "personalDetails" not in profile_details:
        profile_details["personalDetails"] = {}
    
    profile_details["personalDetails"]["primaryEmail"] = newemail

    payload = {
        "request": {
            "userId": user_id,
            "email": newemail,
            "profileDetails": profile_details
        }
    }
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {KB_AUTH_TOKEN}',
    }

    # Make API call with timing
    start_time = time.time()
    try:
        response = requests.request("PATCH", url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
        response_time = time.time() - start_time
        
        # Handle response
        if response.status_code == 200:
            try:
                response_json = response.json()
                
                # Check if the API indicates success
                if response_json.get("params", {}).get("status") == "SUCCESS":
                    return f"Email address updated successfully to {newemail}."
                else:
                    error_msg = response_json.get("params", {}).get("errmsg", "Unknown error")
                    return f"Unable to update email address. Error: {error_msg}"
                    
            except (ValueError, json.JSONDecodeError) as e:
                # If we can't parse JSON but status is 200, assume success
                return f"Email address updated successfully to {newemail}."
        else:
            error_msg = f"API returned status code {response.status_code}"
            return f"Unable to update email address. {error_msg}"
            
    except requests.exceptions.Timeout:
        return "Unable to update email address. Request timed out. Please try again later."
    except requests.exceptions.RequestException as e:
        return f"Unable to update email address due to a network error: {str(e)}"
    except Exception as e:
        return f"Unable to update email address. An unexpected error occurred: {str(e)}"


def get_account_creation_date_tool(tool_context: ToolContext):
    """
    This tool retrieves the account creation date for the user.
    
    Returns:
        A string indicating the account creation date.
    """
    user_id = tool_context.state.get("user_id", None)
    if not user_id:
        return "User ID not available. Please ensure user details are loaded first."
    
    # Get current user details
    profile_details = read_userdetails(user_id)
    if not profile_details:
        return "Unable to fetch the user details, please try again later."
    
    # Extract creation date
    creation_date = profile_details.get("createdDate")
    if creation_date:
        return f"Your account was created on {creation_date}."
    else:
        return "Unable to retrieve your account creation date. The information is not available in your profile."


def get_user_group_tool(tool_context: ToolContext):
    """
    This tool retrieves the user's group/designation information.
    
    Returns:
        A string indicating the user's group and designation.
    """
    user_id = tool_context.state.get("user_id", None)
    if not user_id:
        return "User ID not available. Please ensure user details are loaded first."
    
    # Get current user details
    profile_details = read_userdetails(user_id)
    if not profile_details:
        return "Unable to fetch the user details, please try again later."
    
    # Extract group and designation information
    employment_details = profile_details.get("profileDetails", {}).get("employmentDetails", {})
    professional_details = profile_details.get("profileDetails", {}).get("professionalDetails", [])
    
    department = employment_details.get("departmentName", "")
    designation = ""
    if professional_details and len(professional_details) > 0:
        designation = professional_details[0].get("designation", "")
    
    if department and designation:
        return f"You are mapped to the {department} department with the designation of {designation}."
    elif department:
        return f"You are mapped to the {department} department."
    elif designation:
        return f"Your designation is {designation}."
    else:
        return "Your group and designation information is not available in your profile."


def check_course_completion_status_tool(tool_context: ToolContext):
    """
    This tool checks for courses where completion percentage is 100% but status is still marked as in progress.
    
    Returns:
        A string indicating the courses with completion status issues.
    """
    user_id = tool_context.state.get("user_id", None)
    if not user_id:
        return "User ID not available. Please ensure user details are loaded first."
    
    # Get user details from state
    unified_data = tool_context.state.get("combined_user_details")
    if not unified_data:
        return "User details not loaded. Please use get_combined_user_details_clean_tool first."
    
    course_enrollments = unified_data.get("course_enrollments", [])
    
    problematic_courses = []
    for course in course_enrollments:
        completion_percentage = course.get("completionPercentage", 0)
        completion_status = course.get("status", "")
        course_name = course.get("courseName", "Unknown Course")
        
        if completion_percentage == 100 and completion_status != "completed":
                problematic_courses.append({
                    "name": course_name,
                    "percentage": completion_percentage,
                    "status": completion_status
                })
        

        
        if problematic_courses:
            course_list = "\n".join([f"- {course['name']} (100% complete, status: {course['status']})" 
                                   for course in problematic_courses])
            return f"I found {len(problematic_courses)} course(s) where your completion percentage is 100% but the status is still marked as in progress:\n{course_list}\n\nThis might be due to pending content or certificate issuance. Would you like me to help you resolve this?"
        else:
            return "Great! I checked all your courses and found no issues with completion status. All courses with 100% completion are properly marked as completed."


def get_course_progress_tool(course_name: str, tool_context: ToolContext):
    """
    This tool retrieves the completion progress for a specific course.
    
    Args:
        course_name: The name of the course to check progress for.
    Returns:
        A string indicating the course progress.
    """

    
    user_id = tool_context.state.get("user_id", None)
    if not user_id:
        return "User ID not available. Please ensure user details are loaded first."
    
    # Get user details from state
    unified_data = tool_context.state.get("combined_user_details")
    if not unified_data:
        return "User details not loaded. Please use get_combined_user_details_clean_tool first."
    
    course_enrollments = unified_data.get("course_enrollments", [])
    
    # Find the specific course
    target_course = None
    for course in course_enrollments:
        if course.get("courseName", "").lower() == course_name.lower():
            target_course = course
            break
    
    if not target_course:
        return f"I couldn't find a course named '{course_name}' in your enrollments. Please check the course name and try again."
    
    # Extract progress information
    completion_percentage = target_course.get("completionPercentage", 0)
    completion_status = target_course.get("status", "unknown")
    enrolled_date = target_course.get("enrolledDate", "")
    completed_date = target_course.get("completedOn", "")
    
    # Build response
    response_parts = [f"Course: {target_course.get('courseName')}"]
    response_parts.append(f"Progress: {completion_percentage}% complete")
    response_parts.append(f"Status: {completion_status}")
    
    if enrolled_date:
        response_parts.append(f"Enrolled: {enrolled_date}")
    
    if completed_date and completion_status == "completed":
        response_parts.append(f"Completed: {completed_date}")
    
    # Check for certificate
    if target_course.get("certificateToken"):
        response_parts.append("Certificate: Issued")
    elif completion_percentage == 100:
        response_parts.append("Certificate: Eligible for issuance")
    
    return "\n".join(response_parts)


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
        
        # Extract department, designation, and organization information
        profile_details = user_details.get("profileDetails", {})
        employment_details = profile_details.get("employmentDetails", {})
        professional_details = profile_details.get("professionalDetails", [])
        root_org = user_details.get("rootOrg", {})
        
        # Get department from employment details or root organization
        department = employment_details.get("departmentName", "") or root_org.get("orgName", "")
        
        # Get designation from professional details
        designation = ""
        if professional_details and len(professional_details) > 0:
            designation = professional_details[0].get("designation", "")
        
        # Get organization details
        organization = root_org.get("orgName", "")
        organization_type = root_org.get("sbOrgType", "")
        ministry_or_state = root_org.get("ministryOrStateName", "")

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

        request_body = {
            "request": {
                "retiredCoursesEnabled": True,
                "status": ["In-Progress", "Completed"]
            }
        }
        try:
            # Fetch course enrollments using the configured API endpoint
            logger.info(f"Fetching course enrollments for user: {user_id}")
            
            course_enrollment_url = f"{API_ENDPOINTS['ENROLL']}/{user_id}"
            course_enrollments = []
            user_course_enrollment_info = {}
            
            try:
                logger.info(f"Calling course enrollment API: {course_enrollment_url}")
                # response = requests.get(course_enrollment_url, headers=headers, json=request_body, timeout=30)
                response = requests.post(course_enrollment_url, headers=headers, json=request_body, timeout=30)
                logger.info(f"Course enrollment API response status: {response.status_code}")
                
                if response.status_code == 200:
                    data = response.json()
                    logger.info(f"Course enrollment API response: {data}")
                    
                    # Try different response structures
                    if "result" in data and "courses" in data["result"]:
                        course_enrollments = data["result"]["courses"]
                        user_course_enrollment_info = data["result"].get("userCourseEnrolmentInfo", {})
                    elif "courses" in data:
                        course_enrollments = data["courses"]
                        user_course_enrollment_info = data.get("userCourseEnrolmentInfo", {})
                    elif isinstance(data, list):
                        course_enrollments = data
                    elif "result" in data and isinstance(data["result"], list):
                        course_enrollments = data["result"]
                    
                    logger.info(f"Successfully fetched {len(course_enrollments)} course enrollments")
                    logger.info(f"User course enrollment info: {user_course_enrollment_info}")
                    logger.info(f"Karma points from API: {user_course_enrollment_info.get('karmaPoints', 'NOT_FOUND')}")
                    logger.info(f"Karma points type: {type(user_course_enrollment_info.get('karmaPoints'))}")
                    
                    # Debug: Log the first course structure to understand the data format
                    if course_enrollments and len(course_enrollments) > 0:
                        first_course = course_enrollments[0]
                        logger.info(f"First course structure: {first_course}")
                        logger.info(f"First course keys: {list(first_course.keys()) if isinstance(first_course, dict) else 'Not a dict'}")
                        if isinstance(first_course, dict):
                            logger.info(f"Course name fields: course_name={first_course.get('course_name')}, name={first_course.get('name')}, content.name={first_course.get('content', {}).get('name')}")
                else:
                    logger.warning(f"Course enrollment API failed with status {response.status_code}")
                    logger.warning(f"Response text: {response.text}")
                    
            except Exception as e:
                logger.warning(f"Error fetching course enrollments: {e}")
                logger.warning(f"Exception details: {str(e)}")
            
            # If no course enrollments found from API, try to extract from user profile
            if not course_enrollments and user_details.get("profileDetails", {}).get("systemTopics"):
                logger.info("No course enrollments from API, trying to extract from user profile")
                system_topics = user_details["profileDetails"]["systemTopics"]
                course_enrollments = []
                for topic in system_topics:
                    if topic.get("children"):
                        for child in topic["children"]:
                            if child.get("identifier") and child.get("name"):
                                # Create comprehensive course enrollment object with all expected fields
                                course_enrollment = {
                                    # Basic course information
                                    "course_name": child["name"],
                                    "status": 1,  # Assume in progress
                                    "completionPercentage": child.get("noOfHoursConsumed", 0),
                                    
                                    # Enrollment information
                                    "enrolledDate": user_details.get("createdDate", ""),
                                    
                                    # Content information
                                    "content": {
                                        "name": child["name"],
                                        "identifier": child["identifier"],
                                        "leafNodesCount": child.get("noOfHoursConsumed", 0)
                                    },
                                    
                                    # Batch information (default values)
                                    "batch": {
                                        "startDate": "",
                                        "endDate": "",
                                        "enrollmentEndDate": "",
                                        "status": 1  # active
                                    },
                                    
                                    # Content status (default: not started)
                                    "contentStatus": [0] * max(1, child.get("noOfHoursConsumed", 1)),
                                    
                                    # Certificate information (empty for now)
                                    "issuedCertificates": [],
                                    
                                    # Additional fields
                                    "courseId": child["identifier"],
                                    "completedOn": "",
                                    "leafNodesCount": child.get("noOfHoursConsumed", 0)
                                }
                                course_enrollments.append(course_enrollment)
                logger.info(f"Extracted {len(course_enrollments)} courses from user profile")
            
            # If still no course enrollments, create a default entry based on user profile
            if not course_enrollments:
                logger.info("No course enrollments found, creating default entry")
                course_enrollments = [{
                    # Basic course information
                    "course_name": "Karmayogi Bharat Learning",
                    "status": 1,  # Assume in progress
                    "completionPercentage": 0,
                    
                    # Enrollment information
                    "enrolledDate": user_details.get("createdDate", ""),
                    
                    # Content information
                    "content": {
                        "name": "Karmayogi Bharat Learning",
                        "identifier": "default_course",
                        "leafNodesCount": 1
                    },
                    
                    # Batch information (default values)
                    "batch": {
                        "startDate": "",
                        "endDate": "",
                        "enrollmentEndDate": "",
                        "status": 1  # active
                    },
                    
                    # Content status (default: not started)
                    "contentStatus": [0],
                    
                    # Certificate information (empty for now)
                    "issuedCertificates": [],
                    
                    # Additional fields
                    "courseId": "default_course",
                    "completedOn": "",
                    "leafNodesCount": 1
                }]
                logger.info("Created default course enrollment entry")
            
            print("USER_COURSE_ENROLLMENT_INFO", user_course_enrollment_info, "COURSE_ENROLLMENT", course_enrollments)
            
            # Fetch event enrollments
            event_enrollments = await UserDetailsService()._fetch_event_enrollments(user_id=user_id)
            
            # Simplify event enrollments to only include necessary fields
            if event_enrollments and isinstance(event_enrollments, list):
                simplified_event_enrollments = []
                for event in event_enrollments:
                    if isinstance(event, dict):
                        simplified_event = {
                            # Basic event information
                            "enrolledDate": event.get("enrolledDate"),
                            "status": event.get("status"),
                            "completionPercentage": event.get("completionPercentage"),
                            "completedOn": event.get("completedOn"),
                            "name": event.get("name"),  # Event name at first level
                            
                            # Event information (if available)
                            "event": {
                                "startDateTime": event.get("startDateTime"),
                                "endDateTime": event.get("endDateTime"),
                                "identifier": event.get("identifier")
                            },
                            
                            # User event consumption (simplified)
                            "userEventConsumption": {
                                "completionPercentage": event.get("completionPercentage"),
                                "progressdetails": {
                                    "duration": event.get("duration")
                                }
                            },
                            
                            # Certificate information
                            "issuedCertificates": event.get("issuedCertificates", [])
                        }
                        simplified_event_enrollments.append(simplified_event)
                event_enrollments = simplified_event_enrollments
            
            print("EVENT_ENROLLMENT", event_enrollments)

            # Defensive: Ensure course_enrollments and event_enrollments are lists
            if not isinstance(course_enrollments, list):
                logger.info(f"Expected list for course_enrollments, got {type(course_enrollments)}: {course_enrollments}")
                course_enrollments = []
            if not isinstance(event_enrollments, list):
                logger.info(f"Expected list for event_enrollments, got {type(event_enrollments)}: {event_enrollments}")
                event_enrollments = []

            # Process course enrollments directly to preserve course names
            cleaned_course_enrollments = []
            logger.info(f"Processing {len(course_enrollments)} course enrollments directly")
            
            for course in course_enrollments:
                if isinstance(course, dict):
                    processed_course = {}
                    
                    # Extract course name from courseName or content.name
                    course_name = course.get("courseName") or course.get("content", {}).get("name", "Unknown Course")
                    processed_course["courseName"] = course_name
                    
                    # Extract completion percentage
                    completion_percentage = course.get("completionPercentage", 0)
                    processed_course["completionPercentage"] = completion_percentage
                    
                    # Extract status and convert to readable format
                    status = course.get("status", 0)
                    if status == 0:
                        processed_course["status"] = "not started"
                    elif status == 1:
                        processed_course["status"] = "in progress"
                    elif status == 2:
                        processed_course["status"] = "completed"
                    else:
                        processed_course["status"] = "unknown"
                    
                    # Extract enrollment date
                    enrolled_date = course.get("enrolledDate")
                    if enrolled_date:
                        processed_course["enrolledDate"] = enrolled_date
                    
                    # Extract course ID
                    course_id = course.get("courseId") or course.get("content", {}).get("identifier")
                    if course_id:
                        processed_course["courseId"] = course_id
                    
                    # Extract completion date
                    completed_on = course.get("completedOn")
                    if completed_on:
                        processed_course["completedOn"] = completed_on
                    
                    # Extract leaf nodes count
                    leaf_nodes_count = course.get("leafNodesCount") or course.get("content", {}).get("leafNodesCount")
                    if leaf_nodes_count:
                        processed_course["leafNodesCount"] = leaf_nodes_count
                    
                    # Extract content status for progress calculation
                    content_status = course.get("contentStatus", {})
                    if isinstance(content_status, dict):
                        completed_count = sum(1 for status in content_status.values() if status == 2)
                        if completed_count > 0:
                            processed_course["completedContentCount"] = completed_count
                    
                    # Extract certificate information
                    issued_certificates = course.get("issuedCertificates", [])
                    if issued_certificates and len(issued_certificates) > 0:
                        first_cert = issued_certificates[0]
                        if isinstance(first_cert, dict):
                            if first_cert.get("token"):
                                processed_course["certificateToken"] = first_cert["token"]
                            if first_cert.get("lastIssuedOn"):
                                processed_course["certificateIssuedOn"] = first_cert["lastIssuedOn"]
                    
                    # Extract progress (number of completed modules)
                    progress = course.get("progress", 0)
                    processed_course["progress"] = progress
                    
                    # Extract active status
                    active = course.get("active", True)
                    processed_course["active"] = active
                    
                    cleaned_course_enrollments.append(processed_course)
                    logger.info(f"Processed course: {course_name} (Status: {processed_course['status']}, Progress: {completion_percentage}%)")
            
            print("PROCESSED_COURSES", cleaned_course_enrollments)
            
            # Process event enrollments manually to ensure proper status conversion
            cleaned_event_enrollments = []
            for event in event_enrollments:
                if isinstance(event, dict):
                    processed_event = {}
                    
                    # Extract event name
                    event_name = event.get("eventName") or event.get("name", "Unknown Event")
                    processed_event["eventName"] = event_name
                    
                    # Extract completion percentage
                    completion_percentage = event.get("completionPercentage", 0)
                    processed_event["completionPercentage"] = completion_percentage
                    
                    # Extract status and convert to readable format
                    status = event.get("status", 0)
                    if status == 0:
                        processed_event["status"] = "not started"
                    elif status == 1:
                        processed_event["status"] = "in progress"
                    elif status == 2:
                        processed_event["status"] = "completed"
                    else:
                        processed_event["status"] = "unknown"
                    
                    # Extract enrollment date
                    enrolled_date = event.get("enrolledDate")
                    if enrolled_date:
                        processed_event["enrolledDate"] = enrolled_date
                    
                    # Extract completion date
                    completed_on = event.get("completedOn")
                    if completed_on:
                        processed_event["completedOn"] = completed_on
                    
                    # Extract progress (number of completed modules)
                    progress = event.get("progress", 0)
                    processed_event["progress"] = progress
                    
                    # Extract active status
                    active = event.get("active", True)
                    processed_event["active"] = active
                    
                    # Extract certificate information
                    issued_certificates = event.get("issuedCertificates", [])
                    if issued_certificates and len(issued_certificates) > 0:
                        first_cert = issued_certificates[0]
                        if isinstance(first_cert, dict):
                            if first_cert.get("token"):
                                processed_event["certificateToken"] = first_cert["token"]
                            if first_cert.get("lastIssuedOn"):
                                processed_event["certificateIssuedOn"] = first_cert["lastIssuedOn"]
                    
                    cleaned_event_enrollments.append(processed_event)
                    logger.info(f"Processed event: {event_name} (Status: {processed_event['status']}, Progress: {completion_percentage}%)")
            
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

            # Extract and log karma points
            karma_points_from_api = user_course_enrollment_info.get("karmaPoints", 0)
            logger.info(f"Karma points extracted from API: {karma_points_from_api}")
            logger.info(f"Karma points type: {type(karma_points_from_api)}")
            
            user.karma_points = karma_points_from_api
            logger.info(f"Karma points assigned to user object: {user.karma_points}")

            # Create unified JSON object combining user, enrollment summary, and course enrollments
            unified_user_data = {
                "user_details": {
                    "userId": user.userId,
                    "firstName": user.firstName,
                    "lastName": user.lastName,
                    "primaryEmail": user.primaryEmail,
                    "phone": user.phone,
                    "department": department,
                    "designation": designation,
                    "organization": organization,
                    "organization_type": organization_type,
                    "ministry_or_state": ministry_or_state,
                    # "karmaPoints": user_course_enrollment_info.get("karmaPoints", 0),
                    "karma_points": user.karma_points,
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

            print("UNIFIED_USER_DATA", unified_user_data)
            logger.info(f"Final karma points in unified data: {unified_user_data.get('user_details', {}).get('karma_points', 'NOT_FOUND')}")
            logger.info(f"User object karma points: {user.karma_points}")
            logger.info(f"User course enrollment info karma points: {user_course_enrollment_info.get('karmaPoints', 'NOT_FOUND')}")

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
                    "department": department,
                    "designation": designation,
                    "organization": organization,
                    "course_count": len(updated_course_enrollments),
                    "event_count": len(updated_event_enrollments),
                    "total_enrollments": len(updated_course_enrollments) + len(updated_event_enrollments),
                    "last_updated": time.time()
                }
                
                logger.info(f"Stored unified user data in Redis and state for user: {user_id}")
                
            except Exception as e:
                logger.error(f"Failed to store unified user data: {e}")

            # Create a summary message for the user
            course_count = len(updated_course_enrollments)
            event_count = len(updated_event_enrollments)
            karma_points = user.karma_points or 0
            
            # Create a comprehensive summary including department and designation
            summary_parts = [f"Found your details! You have {course_count} courses and {event_count} events enrolled."]
            
            if department:
                summary_parts.append(f"Department: {department}")
            if designation:
                summary_parts.append(f"Designation: {designation}")
            if organization:
                summary_parts.append(f"Organization: {organization}")
            
            summary_parts.append(f"Your karma points: {karma_points}.")
            
            summary_message = " ".join(summary_parts)
            
            # return [("system", "remember following json details for future response " + json.dumps(unified_user_data, indent=2)),
            # return [("system", "remember following json details for future response " + json.dumps(user.to_json(), indent=2)),
            return [("system", "remember following json details for future response " + str(user)),
                    ("assistant", summary_message)]

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


async def get_combined_user_details_clean_tool(tool_context: ToolContext, force_refresh: bool = False):
    """
    Clean and readable version of get_combined_user_details_tool that maintains the same API structure.
    
    This tool combines fetch_userdetails and load_details_for_registered_users functionality
    into a single operation and stores the result in Redis for efficient access.
    
    Args:
        tool_context: ToolContext object containing user_id and other state information
        force_refresh: If True, forces a fresh fetch from the API even if cached data exists
        
    Returns:
        A tuple containing system message with user details and assistant confirmation message
    """
    
    def fetch_user_profile(user_id: str):
        """Fetch user profile details from the API"""
        url = API_ENDPOINTS['PROFILE'] + user_id
        print("URL", url)
        
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {KB_AUTH_TOKEN}"
        }

        filters = {}
        identifier = user_id
        filters["id"] = user_id
        data = {
            "request": {
                "filters": filters,
                "limit": 1
            }
        }

        response = requests.get(url=url, headers=headers)
        resp_json = response.json()
        print(resp_json)
        
        user_details = resp_json.get("result", {}).get("response", {})
        if not (response.status_code == 200 and resp_json["params"]["status"] == "SUCCESS") or not user_details:
            return None, f"{identifier} is not registered. We can't help you with registered account but you can still ask general questions."
            
        return user_details, None
    
    def extract_user_information(user_details):
        """Extract and organize user information from API response"""
        # Create user object
        user = Userdetails()
        user.userId = user_details.get("userId", "")
        user.firstName = user_details.get("firstName", "")
        user.lastName = user_details.get("lastName", "")
        user.primaryEmail = user_details.get("profileDetails", {}).get("personalDetails", {}).get("primaryEmail", "")
        user.phone = user_details.get("profileDetails", {}).get("personalDetails", {}).get("mobile", "")
        
        # Extract department, designation, and organization information
        profile_details = user_details.get("profileDetails", {})
        employment_details = profile_details.get("employmentDetails", {})
        professional_details = profile_details.get("professionalDetails", [])
        root_org = user_details.get("rootOrg", {})
        
        # Get department from employment details or root organization
        department = employment_details.get("departmentName", "") or root_org.get("orgName", "")
        
        # Get designation from professional details
        designation = ""
        if professional_details and len(professional_details) > 0:
            designation = professional_details[0].get("designation", "")
        
        # Get organization details
        organization = root_org.get("orgName", "")
        organization_type = root_org.get("sbOrgType", "")
        ministry_or_state = root_org.get("ministryOrStateName", "")
        
        return user, {
            "department": department,
            "designation": designation,
            "organization": organization,
            "organization_type": organization_type,
            "ministry_or_state": ministry_or_state
        }
    
    def fetch_course_enrollments(user_id: str):
        """Fetch course enrollments from the API using the current format"""
        url = f"{API_ENDPOINTS['ENROLL']}/{user_id}"
        print("URL", url)

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {KB_AUTH_TOKEN}"
        }

        request_body = {
            "request": {
                "retiredCoursesEnabled": True,
                "status": ["In-Progress", "Completed"]
            }
        }
        
        try:
            logger.info(f"Fetching course enrollments for user: {user_id}")
            course_enrollment_url = f"{API_ENDPOINTS['ENROLL']}/{user_id}"
            course_enrollments = []
            user_course_enrollment_info = {}
            
            logger.info(f"Calling course enrollment API: {course_enrollment_url}")
            response = requests.post(course_enrollment_url, headers=headers, json=request_body, timeout=30)
            logger.info(f"Course enrollment API response status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                
                # Try different response structures
                if "result" in data and "courses" in data["result"]:
                    course_enrollments = data["result"]["courses"]
                    user_course_enrollment_info = data["result"].get("userCourseEnrolmentInfo", {})
                elif "courses" in data:
                    course_enrollments = data["courses"]
                    user_course_enrollment_info = data.get("userCourseEnrolmentInfo", {})
                elif isinstance(data, list):
                    course_enrollments = data
                elif "result" in data and isinstance(data["result"], list):
                    course_enrollments = data["result"]
                
                logger.info(f"Successfully fetched {len(course_enrollments)} course enrollments")
                logger.info(f"User course enrollment info: {user_course_enrollment_info}")
                logger.info(f"Karma points from API: {user_course_enrollment_info.get('karmaPoints', 'NOT_FOUND')}")
                logger.info(f"Karma points type: {type(user_course_enrollment_info.get('karmaPoints'))}")
            else:
                logger.warning(f"Course enrollment API failed with status {response.status_code}")
                logger.warning(f"Response text: {response.text}")
                
        except Exception as e:
            logger.warning(f"Error fetching course enrollments: {e}")
            logger.warning(f"Exception details: {str(e)}")
        
        return course_enrollments, user_course_enrollment_info
    
    def extract_courses_from_profile(user_details, course_enrollments):
        """Extract course information from user profile if API returns empty"""
        if not course_enrollments and user_details.get("profileDetails", {}).get("systemTopics"):
            logger.info("No course enrollments from API, trying to extract from user profile")
            system_topics = user_details["profileDetails"]["systemTopics"]
            course_enrollments = []
            
            for topic in system_topics:
                if topic.get("children"):
                    for child in topic["children"]:
                        if child.get("identifier") and (child.get("name") or child.get("title")):
                            # Try to get course name from multiple possible fields
                            course_name = child.get("name") or child.get("title") or child.get("displayName") or "Unknown Course"
                            course_enrollment = {
                                "courseName": course_name,
                                "status": 1,  # Assume in progress
                                "completionPercentage": child.get("noOfHoursConsumed", 0),
                                "enrolledDate": user_details.get("createdDate", ""),
                                "content": {
                                    "name": course_name,
                                    "identifier": child["identifier"],
                                    "leafNodesCount": child.get("noOfHoursConsumed", 0)
                                },
                                "batch": {
                                    "startDate": "",
                                    "endDate": "",
                                    "enrollmentEndDate": "",
                                    "status": 1  # active
                                },
                                "contentStatus": [0] * max(1, child.get("noOfHoursConsumed", 1)),
                                "issuedCertificates": [],
                                "courseId": child["identifier"],
                                "completedOn": "",
                                "leafNodesCount": child.get("noOfHoursConsumed", 0)
                            }
                            course_enrollments.append(course_enrollment)
            
            logger.info(f"Extracted {len(course_enrollments)} courses from user profile")
        
        return course_enrollments
    
    
    def fetch_event_enrollments(user_id: str):
        """Fetch event enrollments from the API"""
        url = f"{API_ENDPOINTS['EVENTS']}/{user_id}"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {KB_AUTH_TOKEN}"
        }
        
        try:
            logger.info(f"Calling event enrollment API: {url}")
            # response = requests.get(url, headers=headers, timeout=30)
            response = requests.post(url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                print("_"*100)
                print("\n\n\n\n\nEvents RESPONSE", data)
                print("_"*100)
                enrollments_result = data.get("result", {}) if "result" in data else data
                enrollments = enrollments_result.get("events", [])
                logger.info(f"Fetched {len(enrollments)} event enrollments")
                
                # Simplify event enrollments to only include necessary fields
                if enrollments and isinstance(enrollments, list):
                    simplified_event_enrollments = []
                    for event in enrollments:
                        if isinstance(event, dict):
                            simplified_event = {
                                "enrolledDate": event.get("enrolledDate"),
                                "status": event.get("status"),
                                "completionPercentage": event.get("completionPercentage"),
                                "completedOn": event.get("completedOn"),
                                "eventName": event.get("event",{}).get("name"),  # Event name at first level
                                "event": {
                                    "startDateTime": event.get("startDateTime"),
                                    "endDateTime": event.get("endDateTime"),
                                    "identifier": event.get("identifier")
                                },
                                "userEventConsumption": {
                                    "completionPercentage": event.get("completionPercentage"),
                                    "progressdetails": {
                                        "duration": event.get("duration")
                                    }
                                },
                                "issuedCertificates": event.get("issuedCertificates", [])
                            }
                            simplified_event_enrollments.append(simplified_event)
                    enrollments = simplified_event_enrollments
                
                return enrollments if isinstance(enrollments, list) else []
            elif response.status_code == 401:
                logger.error("Event enrollment API: Authentication failed")
                return []
            else:
                logger.error(f"Event enrollment API failed with status {response.status_code}")
                return []
                
        except requests.exceptions.Timeout:
            logger.error("Event enrollment API request timed out")
            return []
        except requests.exceptions.RequestException as e:
            logger.error(f"Event enrollment API request failed: {str(e)}")
            return []
        except Exception as e:
            logger.error(f"Error fetching event enrollments: {e}")
            return []
    
    def process_enrollment_data(course_enrollments, event_enrollments, user_course_enrollment_info):
        """Process and clean enrollment data"""
        
        if not isinstance(course_enrollments, list):
            logger.info(f"Expected list for course_enrollments, got {type(course_enrollments)}: {course_enrollments}")
            course_enrollments = []
        if not isinstance(event_enrollments, list):
            logger.info(f"Expected list for event_enrollments, got {type(event_enrollments)}: {event_enrollments}")
            event_enrollments = []

        # Clean course enrollments
        cleaned_course_enrollments = clean_course_enrollment_data(course_enrollments)
        print("CLEANED_COURSES", cleaned_course_enrollments)
        
        # Manually process course enrollments to ensure proper status conversion
        processed_course_enrollments = []
        for course in cleaned_course_enrollments:
            if isinstance(course, dict):
                processed_course = {}
                
                # Copy all existing fields
                for key, value in course.items():
                    processed_course[key] = value
                
                # Ensure course name is available
                if not processed_course.get("courseName"):
                    if processed_course.get("content", {}).get("name"):
                        processed_course["courseName"] = processed_course["content"]["name"]
                    elif processed_course.get("name"):
                        processed_course["courseName"] = processed_course["name"]
                    else:
                        processed_course["courseName"] = "Unknown Course"
                
                # Convert status to readable format if it's still numeric
                status = processed_course.get("status")
                if isinstance(status, int):
                    if status == 0:
                        processed_course["status"] = "not started"
                    elif status == 1:
                        processed_course["status"] = "in progress"
                    elif status == 2:
                        processed_course["status"] = "completed"
                    else:
                        processed_course["status"] = "unknown"
                
                # Also check course_completion_status field if it exists
                completion_status = processed_course.get("course_completion_status")
                if isinstance(completion_status, int):
                    if completion_status == 0:
                        processed_course["course_completion_status"] = "not started"
                    elif completion_status == 1:
                        processed_course["course_completion_status"] = "in progress"
                    elif completion_status == 2:
                        processed_course["course_completion_status"] = "completed"
                    else:
                        processed_course["course_completion_status"] = "unknown"
                
                processed_course_enrollments.append(processed_course)
                logger.info(f"Processed course: {processed_course.get('courseName', 'Unknown')} - Status: {processed_course.get('status', 'unknown')}")
            else:
                processed_course_enrollments.append(course)
        
        cleaned_course_enrollments = processed_course_enrollments
        
        
        # Clean event enrollments
        cleaned_event_enrollments = [
            event for event in clean_event_enrollment_data(event_enrollments)
            if isinstance(event, dict)
        ]
        print("CLEANED_EVENT", cleaned_event_enrollments)
        
        # Manually process event enrollments to ensure proper status conversion
        processed_event_enrollments = []
        for event in cleaned_event_enrollments:
            if isinstance(event, dict):
                processed_event = {}
                
                # Copy all existing fields
                for key, value in event.items():
                    processed_event[key] = value
                
                # Convert status to readable format if it's still numeric
                status = processed_event.get("status")
                if isinstance(status, int):
                    if status == 0:
                        processed_event["status"] = "not started"
                    elif status == 1:
                        processed_event["status"] = "in progress"
                    elif status == 2:
                        processed_event["status"] = "completed"
                    else:
                        processed_event["status"] = "unknown"
                
                # Also check event_completion_status field if it exists
                completion_status = processed_event.get("event_completion_status")
                if isinstance(completion_status, int):
                    if completion_status == 0:
                        processed_event["event_completion_status"] = "not started"
                    elif completion_status == 1:
                        processed_event["event_completion_status"] = "in progress"
                    elif completion_status == 2:
                        processed_event["event_completion_status"] = "completed"
                    else:
                        processed_event["event_completion_status"] = "unknown"
                
                processed_event_enrollments.append(processed_event)
                logger.info(f"Processed event: {processed_event.get('eventName', 'Unknown')} - Status: {processed_event.get('status', 'unknown')}")
            else:
                processed_event_enrollments.append(event)
        
        cleaned_event_enrollments = processed_event_enrollments

        # Create summaries
        course_summary = course_enrollments_summary(user_course_enrollment_info, cleaned_course_enrollments)
        event_summary = event_enrollments_summary(cleaned_event_enrollments)
        combined_enrollment_summary = create_combined_enrollment_summary(course_summary, event_summary)

        # Remove null/empty values
        updated_course_enrollments = [
            {k: v for k, v in course.items() if v not in [None, '', [], {}]}
            for course in cleaned_course_enrollments
        ]
        updated_event_enrollments = [
            {k: v for k, v in event.items() if v not in [None, '', [], {}]}
            for event in cleaned_event_enrollments
        ]
        
        return updated_course_enrollments, updated_event_enrollments, combined_enrollment_summary
    
    def create_unified_data(user, org_info, course_enrollments, event_enrollments, 
                          combined_summary, user_course_enrollment_info, user_id):
        """Create the unified data structure"""
        # Extract karma points
        karma_points_from_api = user_course_enrollment_info.get("karmaPoints", 0)
        logger.info(f"Karma points extracted from API: {karma_points_from_api}")
        logger.info(f"Karma points type: {type(karma_points_from_api)}")
        
        user.karma_points = karma_points_from_api
        logger.info(f"Karma points assigned to user object: {user.karma_points}")

        unified_user_data = {
            "user_details": {
                "userId": user.userId,
                "firstName": user.firstName,
                "lastName": user.lastName,
                "primaryEmail": user.primaryEmail,
                "phone": user.phone,
                "department": org_info["department"],
                "designation": org_info["designation"],
                "organization": org_info["organization"],
                "organization_type": org_info["organization_type"],
                "ministry_or_state": org_info["ministry_or_state"],
                "karma_points": user.karma_points,
            },
            "combined_enrollment_summary": combined_summary,
            "course_enrollments": course_enrollments,
            "event_enrollments": event_enrollments,
            "metadata": {
                "total_courses": len(course_enrollments),
                "total_events": len(event_enrollments),
                "total_enrollments": len(course_enrollments) + len(event_enrollments),
                "timestamp": time.time(),
                "user_id": user_id
            }
        }
        
        print("UNIFIED_USER_DATA", unified_user_data)
        logger.info(f"Final karma points in unified data: {unified_user_data.get('user_details', {}).get('karma_points', 'NOT_FOUND')}")
        logger.info(f"User object karma points: {user.karma_points}")
        logger.info(f"User course enrollment info karma points: {user_course_enrollment_info.get('karmaPoints', 'NOT_FOUND')}")
        
        return unified_user_data
    
    def store_data_in_cache(unified_data, user, org_info, course_enrollments, event_enrollments, user_id):
        """Store data in Redis and tool context"""
        try:
            # Generate cache key
            cache_key = f"combined_user_details:{user_id}"
            ttl_seconds = 30 * 60  # 30 minutes default TTL
            
            # Store in tool context (this doesn't require Redis)
            tool_context.state['combined_user_details'] = unified_data
            tool_context.state['user_summary'] = {
                "user_id": user.userId,
                "first_name": user.firstName,
                "last_name": user.lastName,
                "department": org_info["department"],
                "designation": org_info["designation"],
                "organization": org_info["organization"],
                "course_count": len(course_enrollments),
                "event_count": len(event_enrollments),
                "total_enrollments": len(course_enrollments) + len(event_enrollments),
                "last_updated": time.time()
            }
            
            logger.info(f"Stored unified user data in tool context for user: {user_id}")
            
            # Try to store in Redis if available (optional)
            try:
                import redis
                redis_host = os.getenv('REDIS_HOST', 'localhost')
                redis_port = int(os.getenv('REDIS_PORT', 6379))
                redis_db = int(os.getenv('REDIS_DB', 0))
                
                redis_client = redis.Redis(host=redis_host, port=redis_port, db=redis_db, decode_responses=True)
                redis_client.setex(cache_key, ttl_seconds, json.dumps(unified_data))
                logger.info(f"Stored unified user data in Redis for user: {user_id}")
                
            except Exception as redis_error:
                logger.warning(f"Redis storage failed (optional): {redis_error}")
            
        except Exception as e:
            logger.error(f"Failed to store unified user data: {e}")
    
    def create_response_message(course_count, event_count, karma_points, org_info):
        """Create the response message for the user"""
        summary_parts = [f"Found your details! You have {course_count} courses and {event_count} events enrolled."]
        
        if org_info["department"]:
            summary_parts.append(f"Department: {org_info['department']}")
        if org_info["designation"]:
            summary_parts.append(f"Designation: {org_info['designation']}")
        if org_info["organization"]:
            summary_parts.append(f"Organization: {org_info['organization']}")
        
        summary_parts.append(f"Your karma points: {karma_points}.")
        
        return " ".join(summary_parts)
    
    # Main execution flow
    try:
        user_id = tool_context.state.get("user_id")
        
        if not user_id:
            return "Unable to load user ID, please try again later."
        
        # Step 1: Fetch user profile
        user_details, error_message = fetch_user_profile(user_id)
        if error_message:
            return error_message
        
        # Step 2: Extract user information
        user, org_info = extract_user_information(user_details)
        
        # Store basic user details in state
        tool_context.state['validuser'] = True
        tool_context.state['userdetails'] = dict(user)
        tool_context.state['loaded_details'] = True
        
        # Step 3: Fetch course enrollments
        course_enrollments, user_course_enrollment_info = fetch_course_enrollments(user_id)
        
        # Step 4: Extract courses from profile if needed
        course_enrollments = extract_courses_from_profile(user_details, course_enrollments)
        
        # Step 5: Fetch event enrollments
        event_enrollments = fetch_event_enrollments(user_id)
        print("RAW EVENT ENROLLMENTS:", event_enrollments)
        
        # Step 6: Process enrollment data
        updated_course_enrollments, updated_event_enrollments, combined_enrollment_summary = process_enrollment_data(
            course_enrollments, event_enrollments, user_course_enrollment_info
        )
        
        # Step 7: Create unified data
        unified_user_data = create_unified_data(
            user, org_info, updated_course_enrollments, updated_event_enrollments,
            combined_enrollment_summary, user_course_enrollment_info, user_id
        )
        
        # Step 8: Store data in cache
        store_data_in_cache(
            unified_user_data, user, org_info, updated_course_enrollments, 
            updated_event_enrollments, user_id
        )
        
        # Step 9: Create response message
        course_count = len(updated_course_enrollments)
        event_count = len(updated_event_enrollments)
        karma_points = user.karma_points or 0
        response_message = create_response_message(course_count, event_count, karma_points, org_info)
        
        return [("system", "remember following json details for future response " + str(user)),
                ("assistant", response_message)]
        
    except Exception as e:
        logger.error(f"Error in get_combined_user_details_clean_tool: {e}")
        return f"Unable to fetch user details, please try again later. Error: {str(e)}"


async def answer_course_event_questions(tool_context: ToolContext, question: str):
    """
    This tool uses Ollama to answer user questions about their courses and events.
    It leverages the unified user data stored in Redis or tool context to provide
    personalized responses.
    
    Args:
        tool_context: ToolContext object containing user_id and other state information
        question: The user's question about their courses or events
        
    Returns:
        A structured response with the answer to the user's question
    """
    try:
        user_id = tool_context.state.get("user_id")
        if not user_id:
            return {
                "parts": [{"text": "User ID not available. Please ensure user details are loaded first."}],
                "role": "model"
            }
        
        # Get combined user details from Redis or state
        unified_data = tool_context.state.get("combined_user_details")
        print("UNIFIED_DATA", unified_data)
        if not unified_data:
            return {
                "parts": [{"text": "User details not loaded. Please use get_combined_user_details_clean_tool first."}],
                "role": "model"
            }
        
        course_enrollments = unified_data.get("course_enrollments", [])
        event_enrollments = unified_data.get("event_enrollments", [])
        
        # Debug: Check event enrollments in answer function
        print(f"Event enrollments count: {len(event_enrollments)}")
        for i, event in enumerate(event_enrollments):
            event_name = event.get('eventName', 'NO_EVENT_NAME')
            print(f"Answer function - Event {i+1} name: {event_name}")
            print(f"Answer function - Event {i+1} keys: {list(event.keys())}")
        
        # Construct a prompt for the LLM
        prompt_template = """
        You are a helpful assistant for the Karmayogi Bharat platform. You have access to the user's course and event enrollment data.

        User Details:
        {user_details}

        Course Enrollments:
        {course_enrollments}

        Event Enrollments:
        {event_enrollments}

        User Question: {question}

        Please provide a helpful, accurate, and personalized response based on the user's data. 
        If the user asks about specific courses or events, use the actual names from their enrollments.
        If they ask about completion status, use the actual completion percentages and statuses.
        If they ask about certificates, check if they have issued certificates.
        Be conversational and helpful.

        Answer:
        """
        # print("PROMPT_TEMPLATE", prompt_template)
        
        course_enrollments_str = "\n".join([
            f"- {course.get('courseName', 'Unknown Course')}: {course.get('completionPercentage', 0)}% complete, Status: {course.get('status', 'unknown')}"
            for course in course_enrollments
        ])
        
        event_enrollments_str = "\n".join([
            f"- {event.get('eventName', 'Unknown Event')}: {event.get('completionPercentage', 0)}% complete, Status: {event.get('status', 'unknown')}"
            for event in event_enrollments
        ])
        
        user_details = unified_data.get("user_details", {})
        user_details_str = f"""
            Name: {user_details.get('firstName', '')} {user_details.get('lastName', '')}
            Department: {user_details.get('department', 'Not specified')}
            Designation: {user_details.get('designation', 'Not specified')}
            Organization: {user_details.get('organization', 'Not specified')}
            Karma Points: {user_details.get('karma_points', 0)}
        """
        
        # Format the prompt
        formatted_prompt = prompt_template.format(
            user_details=user_details_str,
            course_enrollments=course_enrollments_str,
            event_enrollments=event_enrollments_str,
            question=question
        )
        print("FORMATTED_PROMPT", formatted_prompt)
        # Use Ollama to generate the response
        ollama_url = f"{OLLAMA_BASE_URL}/api/generate"
        headers = {"Content-Type": "application/json"}
        data = {
            "model": OLLAMA_MODEL,
            "prompt": formatted_prompt,
            "stream": False,
            "options": {
                "temperature": 0.7,
                "top_p": 0.7,
                "top_k": 40,
                "num_ctx": 4096,
                "repeat_penalty": 1.1,
                "num_predict": 1024
            }
        }
        
        logger.info(f"Calling Ollama API at: {ollama_url}")
        logger.info(f"Using model: {OLLAMA_MODEL}")
        logger.info(f"Request data: {data}")
        
        response = requests.post(ollama_url, headers=headers, json=data, timeout=REQUEST_TIMEOUT)
        
        if response.status_code == 200:
            response_data = response.json()
            answer = response_data.get("response", "I'm sorry, I couldn't generate a response at the moment.")
            
            logger.info(f"Ollama response received successfully")
            return {
                "parts": [{"text": answer}],
                "role": "model"
            }
        else:
            logger.error(f"Ollama API error: {response.status_code} - {response.text}")
            
            # Provide more specific error messages
            if response.status_code == 404:
                error_msg = "Ollama model not found. Please ensure the model is installed."
            elif response.status_code == 500:
                error_msg = "Ollama server error. Please try again later."
            else:
                error_msg = f"Ollama API error (status {response.status_code}). Please try again later."
            
            return {
                "parts": [{"text": error_msg}],
                "role": "model"
            }
            
    except Exception as e:
        logger.error(f"Error in answer_course_event_questions: {e}")
        return {
            "parts": [{"text": f"An error occurred while processing your question: {str(e)}"}],
            "role": "model"
        }
