"""
This module contains the tools for the Karmayogi Bharat chatbot.
"""
# import json
import re
import os
import datetime

import requests
from dotenv import load_dotenv
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.core import Settings

from ..utils.utils import load_documents, content_search_api, save_tickets
from ..config.config import API_ENDPOINTS, REQUEST_TIMEOUT

# .env configuration
load_dotenv()

# global .env variables
KB_AUTH_TOKEN = os.getenv('KB_AUTH_TOKEN')
KB_DIR = os.getenv("KB_DIR")

# Embedding variables
Settings.embed_model = HuggingFaceEmbedding("sentence-transformers/all-MiniLM-L6-v2")
Settings.llm = None

# Load the knowledge base documents
queryengine = load_documents(KB_DIR)


def create_support_ticket_tool(reason: str, username: str, user_email: str, description: str):
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
        username: The name of the user, retrieved from the user profile.
        user_email: The email address to send the support email from.
        description : last 5 messages of the conversation, which will be used to create the ticket.

    Returns:
        A string indicating the result of the operation.
    """

    print('tool_call: create_support_ticket_tool', reason, user_email)
    # tickets = load_tickets()

    ticket_id = user_email
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

    if save_tickets(ticket_data):
        return "Support ticket has been created with following details"+\
            f" {ticket_data}. Please wait for support team to revert."

    return "Unable to create support ticket, please try again later."


def load_details_for_registered_users(is_registered: bool, user_id : str):
    """
    Once users email address is validated, we load the other details,
    so that we can answer related questions.

    Args:
        is_registered: this is check if validate_email function is called and user is validated.
        user_id: it is fetched from the previous validate_email function call json output. 
    """
    print('tool_call: load_details_for_registered_users', is_registered, user_id)

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
            print(f"Error: {response.status_code} - {response.text}")
            return "Unable to fetch user details, please try again later."
        # Uncomment the next line to raise an exception for bad status codes
        # response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)

        return [ ("system", "remember following json details for future response "\
                  + str(response.json())),
                ("assistant", "Found your details, you can ask questions now.")]

    except requests.exceptions.RequestException as e:
        print(f"Error during API request: {e}")
        return "Unable to fetch user details, please try again later."


def validate_email(email : str):
    """
    This tool validate if the email is registered with Karmayogi bharat portal or not.

    Args:
        email: email provided by user to validate if user is registered or not
    """
    print('tool_call : validate_email')
    if not email:
        return None

    email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'

    if not re.match(email_regex, email):
        return ValueError('Email format is not valid')

    url = API_ENDPOINTS['USER_SEARCH']

    headers = {
        "Accept" : "application/json",
        "Content-Type" : "application/json",
        "Authorization" : f"Bearer {KB_AUTH_TOKEN}"
    }

    data = {
        "request" : {
            "filters" : {
                "email" : email
            },
            "limit" : 1
        }
    }

    response = requests.post(url=url, headers=headers, json=data, timeout=REQUEST_TIMEOUT)
    if response.status_code != 200:
        print(f"Error: {response.status_code} - {response.text}")
        return "Unable to validate email, please try again later."

    if not response.json()["result"]["response"]["content"]:
        return f'User is not registered with {email} you mentioned.'

    if response.status_code == 200 and response.json()["params"]["status"] == "SUCCESS":
        return [("system", "remember following json details for future response "\
                 + str(response.json())),
                 "assistant", "Found user, please wait till we fetch the details."]
    return f"{email} is not registered. \
     We can't help you with registerd account but you can still ask general questions."


def answer_general_questions(userquestion: str):
    """
    This tool help answer the general questions user might have,
    this help can answer the question based knowledge base provided.

    Args:
        userquestion: This argument is question user has asked. This argument can't be empty.
    """
    print('tool_call : answer_general_questions', userquestion)
    try:
        # global queryengine
        response = queryengine.query(userquestion)
        # print('loaded resp: ', type(response))
    except (AttributeError, TypeError, ValueError) as e:
        print('Unable to answer the question due to a specific error:', str(e))
        return "Unable to answer right now, please try again later."

    return str(response)


def handle_certificate_issues(coursename: str, user_id : str):
    """
    This tool help user figure out issued certificate after completion of course enrolled.
    This tool is only invoked/called for registered uses, and after validating user.
    Use this tool only if user is enrolled in the course mentioned, 
    otherwise provide appropriate message and dissmiss the request.

    Args:
        coursename: for which course user want to validate against.
        user_id: This argument is user id of user who wants to get the certification 
        details of his enrolled courses. Make sure to pass right user id, 
        don't pass email id instead
    """
    print('tool_call, handle_certificate_issues', coursename, user_id)

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
            print(f"Error: {response.status_code} - {response.text}")
            return "Unable to fetch user details, please try again later."
        # Uncomment the next line to raise an exception for bad status codes
        # response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)

        # res = response.json()

        courses = response.json().get("result", {}).get("courses", [])

        targetcourse = None
        for course in courses:
            if course.get("courseName").lower() == coursename.lower():
                print("Found course: ", course.get("courseName"))
                targetcourse = course
                break

        completion_percentage = targetcourse.get("completionPercentage")
        issued_certificate = targetcourse.get("issuedCertificate")
        content_status = targetcourse.get("contentStatus", {})

        if completion_percentage == 100 and not issued_certificate:
            # NOTE: following code is not tested, please test before using
            response = ""
            return "Issuing certificate over your mail" + response

        pending_content_ids = [
            content_id for content_id, status in content_status.items()
            if status != 2
        ]

        if pending_content_ids:
            pending_content_names = []
            content_details = content_search_api(pending_content_ids)
            pending_content_names.append(content_details.get("name", "Unknown"))

            return "You seem to have not completed the course components." \
            "Following contents are still pending and in progress" \
            + ", ".join(pending_content_names)
        return "You haven't finished the course components."
    except requests.exceptions.RequestException as e:
        print(f"Error during API request: {e}")
        return "Unable to fetch user details, please try again later."
