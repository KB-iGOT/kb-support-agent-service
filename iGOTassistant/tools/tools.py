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

from pathlib import Path
import requests
from dotenv import load_dotenv
# from llama_index.embeddings.huggingface import HuggingFaceEmbedding
# from llama_index.core import Settings

from google.adk.tools import ToolContext

# from ..utils.utils import load_documents, save_tickets, content_search_api
from ..utils.utils import (load_documents,
                           save_tickets,
                           content_search_api,
                           send_mail_api,
                           raise_ticket_mail)
from ..config.config import API_ENDPOINTS, REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

load_dotenv()
KB_AUTH_TOKEN = os.getenv("KB_AUTH_TOKEN")

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
