"""
This module contains the tools for the Karmayogi Bharat chatbot.
"""
import json
import re
import os
import requests
from dotenv import load_dotenv
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.core import Settings

from utils.utils import load_documents, content_search_api, issue_course_certificate, send_mail_api
from config import API_ENDPOINTS, DEFAULT_HEADERS, REQUEST_TIMEOUT

# .env configuration
load_dotenv()

# global .env variables
BEARER = os.getenv('BEARER')
KB_DIR = os.getenv("KB_DIR")

# Embedding variables
Settings.embed_model = HuggingFaceEmbedding("sentence-transformers/all-MiniLM-L6-v2")
Settings.llm = None

# Load the knowledge base documents
queryengine = load_documents(KB_DIR)


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
        **DEFAULT_HEADERS,
        "Authorization" : f"Bearer {BEARER}"
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
        **DEFAULT_HEADERS,
        "Authorization" : f"Bearer {BEARER}"
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
        global queryengine
        response = queryengine.query(userquestion)
        # print('loaded resp: ', type(response))
    except Exception as e:
        print('Unable to answer the question :', str(e))
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
        **DEFAULT_HEADERS,
        "Authorization" : f"Bearer {BEARER}"
    }

    try:
        response = requests.get(url, headers=headers, timeout=60)
        if response.status_code != 200:
            print(f"Error: {response.status_code} - {response.text}")
            return "Unable to fetch user details, please try again later."
        # Uncomment the next line to raise an exception for bad status codes
        # response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)

        res = response.json()

        courses = res.get("result", {}).get("courses", [])

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
            # NOTE: due to api test issue, this part is removed for now.
            return "Issuing certificate over your mail" + response
        elif completion_percentage < 100:
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

        else:
            return "You haven't finished the course components."


    except requests.exceptions.RequestException as e:
        print(f"Error during API request: {e}")
        return "Unable to fetch user details, please try again later."
