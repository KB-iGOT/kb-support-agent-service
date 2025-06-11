
"""
This module contains the tools for the Karmayogi Bharat chatbot.
"""
# import re
# import sys
import os
# import json
# import datetime
# import uuid
import logging

# from pathlib import Path
import requests
from dotenv import load_dotenv
# from llama_index.embeddings.huggingface import HuggingFaceEmbedding
# from llama_index.core import Settings

from google.adk.tools import ToolContext 

# from ..utils.utils import load_documents, save_tickets, content_search_api
from ..utils.utils import send_mail_api, content_search_api
# from ..utils.utils import (load_documents,
#                            save_tickets,
#                            content_search_api,
#                            send_mail_api,
#                            raise_ticket_mail)
from ..config.config import API_ENDPOINTS, REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

load_dotenv()
KB_AUTH_TOKEN = os.getenv('KB_AUTH_TOKEN')

def handle_certificate_name_issues(tool_context: ToolContext, user_id: str, coursename: str):
    """
    This tool help user with resolution of the name change, name mismatch, name error
    in certificate issued.

    Args:
        user_id: user ID of the user who has issued certificate
        coursename: the certificate issued course, where name is wrong
    """
    if not tool_context.state.get('otp_auth', False):
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


        courses = response.json().get("result", {}).get("courses", [])

        targetcourse = None
        for course in courses:
            if course.get("courseName").lower() == coursename.lower():
                targetcourse = course
                break

        completion_percentage = targetcourse.get("completionPercentage")
        issued_certificate = targetcourse.get("issuedCertificate")
        content_status = targetcourse.get("contentStatus", {})

        if completion_percentage == 100 and not issued_certificate:
            # NOTE: following code is not tested, please test before using
            # logging.info("Trying send a mail")
            # response = send_mail_api(user_id=user_id, coursename=targetcourse.get("courseName"))
            # logging.info('mail resp ', response)
            # return "Issuing new certificate with QR" + response

            ticket_details = {
                "reason": " [IGOT KARMAYOGI ASSISTANT] Incorrect name in certificate",
                "description" : targetcourse.get("courseName") + \
                    "certificate has mistake in user name. Please fix it."
            }

            return "Course is finished, we can raise a ticket with following details" + \
                str(ticket_details)

        pending_content_ids = [
            content_id for content_id, status in content_status.items()
            if status != 2
        ]

        if pending_content_ids:
            pending_content_names = []
            content_details = content_search_api(pending_content_ids)
            pending_content_names = content_details

            return "You seem to have not completed the course components." \
            "Following contents are still pending and in progress" \
            + ", ".join(pending_content_names)
        return "You haven't finished the course components."
    except requests.exceptions.RequestException as e:
        logging.info("Error during API request: %s", e)
        return "Unable to fetch user details, please try again later."



def handle_certificate_qr_issues(tool_context: ToolContext, user_id: str, coursename: str):
    """
    This tool help user solve issues related QR code generated on issued certificate.

    Args:
        user_id: user ID of the user who is facing QR related issues.
        coursename: coursename of the course certificate where the issue persist.
    """
    if not tool_context.state.get('otp_auth', False):
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
        response = requests.get(url, headers=headers, timeout=60)
        if response.status_code != 200:
            # logging.info(f"Error: {response.status_code} - {response.text}")
            return "Unable to fetch user details, please try again later."
        # Uncomment the next line to raise an exception for bad status codes
        # response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)

        courses = response.json().get("result", {}).get("courses", [])

        targetcourse = None
        for course in courses:
            if course.get("courseName").lower() == coursename.lower():
                targetcourse = course
                break

        completion_percentage = targetcourse.get("completionPercentage")
        issued_certificate = targetcourse.get("issuedCertificate")
        content_status = targetcourse.get("contentStatus", {})

        if completion_percentage == 100 and not issued_certificate:
            # NOTE: following code is not tested, please test before using
            logging.info("Trying send a mail")
            response = send_mail_api(user_id=user_id, coursename=targetcourse.get("courseName"))
            return "Issuing new certificate with QR" + response

        pending_content_ids = [
            content_id for content_id, status in content_status.items()
            if status != 2
        ]

        if pending_content_ids:
            pending_content_names = []
            content_details = content_search_api(pending_content_ids)
            pending_content_names = content_details

            return "You seem to have not completed the course components." \
            "Following contents are still pending and in progress" \
            + ", ".join(pending_content_names)
        return "You haven't finished the course components."
    except requests.exceptions.RequestException as e:
        logging.info("Error during API request: %s", e)
        return "Unable to fetch user details, please try again later."


def handle_issued_certificate_issues(tool_context: ToolContext, user_id : str, coursename: str):
    """
    This tool help user figure out issued certificate after completion of course enrolled.
    This tool is only invoked/called for registered uses, and after validating user.
    Use this tool only if user is enrolled in the course mentioned, 
    otherwise provide appropriate message and dissmiss the request.

    Args:
        user_id: This argument is user id of user who wants to get the certification 
            details of his enrolled courses. Make sure to pass right user id, 
            don't pass email id instead
        coursename: for which course user want to validate against.
    """

    if not tool_context.state.get('otp_auth', False):
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

        courses = response.json().get("result", {}).get("courses", [])

        targetcourse = None
        for course in courses:
            if course.get("courseName").lower() == coursename.lower():
                targetcourse = course
                break

        completion_percentage = targetcourse.get("completionPercentage")
        issued_certificate = targetcourse.get("issuedCertificate")
        content_status = targetcourse.get("contentStatus", {})

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
            pending_content_names = content_details

            return "You seem to have not completed the course components." \
            "Following contents are still pending and in progress" \
            + ", ".join(pending_content_names)
        return "You haven't finished the course components."
    except requests.exceptions.RequestException as e:
        logging.info("Error during API request: %s", e)
        return "Unable to fetch user details, please try again later."


def list_pending_contents(tool_context: ToolContext, user_id: str, coursename: str):
    """
    Use this tool when user ask which contents are pending from course XYZ.
    Fetches content details from the Karmayogi Bharat API.
    Args:
        user_id (str): The ID of the user to check for pending contents.
        coursename (str): The name of the course to check for pending contents.
    Returns:
        dict|str: A dictionary containing the content details.
    """

    if not tool_context.state.get('otp_auth', False):
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

        content_status = targetcourse.get("contentStatus", {})


        pending_content_ids = [
            content_id for content_id, status in content_status.items()
            if status != 2
        ]

        if pending_content_ids:
            pending_content_names = []
            content_details = content_search_api(pending_content_ids)
            pending_content_names = content_details

            return "You seem to have not completed the course components." \
            "Following contents are still pending and in progress" \
            + ", ".join(pending_content_names)
        return "You haven't finished the course components."
    except requests.exceptions.RequestException as e:
        logging.info("Error during API request: %s", e)
        return "Unable to fetch user details, please try again later."
    except Exception as e:
        # return {identifier : None for identifier in content_id}
        logging.info("ERR: %s", e)
        return "Unable to load pending contents"
