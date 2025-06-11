"""
This module contains the utility functions for the Karmayogi Bharat chatbot.
"""

import os
import json
import logging
from urllib.parse import urlencode
from typing import Optional, Dict, List, Any
import requests
# from src.tools.tools import KB_AUTH_TOKEN
from llama_index.core import SimpleDirectoryReader, VectorStoreIndex

from ..config.config import API_ENDPOINTS, REQUEST_TIMEOUT, TICKET_DIR, TICKET_FILE

# logger = logging.getLogger(__name__)
logger = logging.getLogger("uvicorn")

# loading the knowledge base from the document directory.
def load_documents(dirname: str):
    """
    Loading the knowledge base documents from a directory and creates a query engine.
    
    Args:
        dirname (str): Path to the directory containing knowledge base documents

    Returns:
        Optional[BaseQueryEngine]: Query engine if successful, None if failed

    Raises:
        FileNotFoundError: If the directory doesn't exist
        PermissionError: If there are permission issues accessing the directory
        ValueError: If the directory is empty or contains no valid documents
        IOError: If there are issues reading the documents
    """
    try:
        # Check if directory exists
        if not os.path.exists(dirname):
            raise FileNotFoundError(f"Directory not found: {dirname}")

        # Check if directory is empty
        if not os.listdir(dirname):
            raise ValueError(f"Directory is empty: {dirname}")

        # Attempt to load documents
        documents = SimpleDirectoryReader(dirname).load_data()
        if not documents:
            raise ValueError(f"No valid documents found in directory: {dirname}")

        logging.info('Documents loaded successfully.')
        # Create index and query engine
        index = VectorStoreIndex.from_documents(documents=documents)
        return index.as_query_engine()

    except FileNotFoundError as e:
        logging.info(f"Directory error: {str(e)}")
    except PermissionError as e:
        logging.info(f"Permission denied: {str(e)}")
    except ValueError as e:
        logging.info(f"Document loading error: {str(e)}")
    except IOError as e:
        logging.info(f"I/O error occurred: {str(e)}")

    return "Unable to load the documents, please try again later."


def get_user_token(
    auth_url: str,  # URL for the auth/token endpoint
    client_id: str,
    username: str,
    password: str
) -> Optional[str]:
    """
    Retrieves the user's access token from the authentication service.

    Args:
        auth_url (str): The URL of the authentication token endpoint.
        client_id (str): The client ID.
        username (str): The user's username.
        password (str): The user's password.

    Returns:
        Optional[str]: The access token if successful, None otherwise.
    """

    payload = {
        "client_id": client_id,
        "grant_type": "password",
        "username": username,
        "password": password
    }
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}

    try:
        response = requests.post(auth_url, headers=headers,
                                 data=urlencode(payload), timeout=REQUEST_TIMEOUT)
        if response.status_code != 200:
            logging.info(f"Error: {response.status_code} - {response.text}")
            return None

        # Uncomment the next line to raise an exception for bad status codes
        # response.raise_for_status()
        return response.json().get("access_token")
    except requests.exceptions.RequestException as e:
        logging.info(f"Error getting user token: {e}")
        return None


def issue_course_certificate(
    api_key: str,
    auth_url: str,
    client_id: str,
    username: str,
    password: str,
    batch_id: str,
    course_id: str,
    user_ids: List[str],
    re_issue: bool = True
) -> Dict[str, Any]:
    """
    Issues or re-issues course certificates to specified users, including user token retrieval.

    Args:
        api_key (str): The API key for the certificate issuance API.
        auth_url (str): The URL of the authentication token endpoint.
        client_id (str): The client ID for authentication.
        username (str): The user's username for authentication.
        password (str): The user's password for authentication.
        batch_id (str): The ID of the course batch.
        course_id (str): The ID of the course.
        user_ids (List[str]): A list of user IDs to issue certificates to.
        re_issue (bool, optional): Whether to re-issue certificates. Defaults to True.

    Returns:
        Dict[str, Any]: The JSON response from the certificate issuance API.
    """

    user_token = get_user_token(auth_url, client_id, username, password)

    if not user_token:
        logging.info("Failed to obtain user token.")
        return "User token not found, please check your credentials."
        # return {}  # Or raise an exception:  raise Exception("Failed to obtain user token")

    cert_url = API_ENDPOINTS["CERTIFICATE"] + f"?reIssue={str(re_issue).lower()}"
    cert_headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "x-authenticated-user-token": user_token,
    }
    cert_payload = {
        "request": {
            "batchId": batch_id,
            "courseId": course_id,
            "userIds": user_ids
        }
    }

    try:
        response = requests.post(cert_url, headers=cert_headers,
                                 data=json.dumps(cert_payload), timeout=60)

        if response.status_code != 200:
            logging.info(f"Error: {response.status_code} - {response.text}")
            return {}

        # Uncomment the next line to raise an exception for bad status codes
        # response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.info(f"Error issuing certificate: {e}")
        return {}

def send_mail_api(user_id, coursename):
    """
    Sends an email notification using the Karmayogi Bharat API.
    Args:
        None
    Returns:
        str: A message indicating the success of the email sending operation.
    """
    url = API_ENDPOINTS["EMAIL"]
    KB_AUTH_TOKEN = os.getenv("KB_AUTH_TOKEN")

    payload = json.dumps({
    "request": {
        "body": f"\n\nUser with user-id: {user_id} has not received"\
        f" course completion certificate for course: {coursename} \n"\
        "\n\nPlease check the details.",
        "mode": "email",
        "subject": "BOT SUPPORT - Certificate not generated!",
        "recipientEmails": [
        "jayaprakash.n@tarento.com"
        ],
        "firstName": "Support Team"
    }
    })
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {KB_AUTH_TOKEN}',
    }


    response = requests.request("POST", url, headers=headers, data=payload, timeout=60)
    if response.status_code == 200: 
        return "Email sent successfully: " + response.text
    return "Failed to trigger the mail"


def raise_ticket_mail(user_id, ticket_details):
    """
    Sends an email notification using the Karmayogi Bharat API.
    Args:
        None
    Returns:
        str: A message indicating the success of the email sending operation.
    """
    url = API_ENDPOINTS["EMAIL"]
    KB_AUTH_TOKEN = os.getenv("KB_AUTH_TOKEN")

    payload = json.dumps({
    "request": {
        "body": f"\n\nUser with user-id: {user_id} raised ticket "\
            "with details \n\n" + str(ticket_details) + \
            "\n\nPlease check the details.",
        "mode": "email",
        "subject": "[KB Support Assistant] TICKET: " + str(ticket_details["username"]) + " and user id: " + str(user_id),   # f"BOT SUPPORT - {ticket_details['username']} Raised with {ticket_details['reason']} ",
        "recipientEmails": [
        "mission.karmayogi@gov.in"
        ],
        "firstName": "Support Team"
    }
    })
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {KB_AUTH_TOKEN}',
    }

    response = requests.request("POST", url, headers=headers, data=payload, timeout=60)
    if response.status_code == 200:
        return "Email sent successfully: " + response.text
    return "Failed to trigger the mail"

def content_search_api(content_id):
    """
    Use this tool when user ask which contents are pending from course XYZ.
    Fetches content details from the Karmayogi Bharat API.
    Args:
        content_id (str): The content identifier to search for.
    Returns:
        dict|str: A dictionary containing the content details.
    """
    logging.info('tool_call: content_search_api', content_id)
    url = API_ENDPOINTS["CONTENT_SEARCH"]
    headers = {'Content-Type': 'application/json'}
    payload = {
        "request": {
            "filters": {
                "status": [],
                "identifier": content_id
            },
            "isSecureSettingsDisabled": True,
            "fields": ["identifier", "status", "name"],
            "limit": 2000
        }
    }

    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=60)
        logging.info('response ', response.json())

        if response.status_code != 200:
            logging.info(f"Error: {response.status_code} - {response.text}")
            return "Failed to load the contents"
            # return {identifier : None for identifier in content_id}

        # Uncomment the next line to raise an exception for bad status codes
        # response.raise_for_status()  # Raise an exception for bad status codes

        response_data = response.json()
        contents = response_data.get("result", {}).get("content", [])  # Safely access content list

        logging.info('contents ', contents)

        #  Index content by identifier for easy lookup
        content_map = [content.get("name", "Unknown") for content in contents]
        return content_map

    except requests.exceptions.RequestException as e:
        logging.info("Error calling the content search API", str(e))
        return {identifier : None for identifier in content_id}


def load_tickets():
    """
    Loads tickets from a JSON file.
    
    Returns:
        list: A list of tickets loaded in dictionary format.
    """
    if not os.path.exists(TICKET_DIR):
        os.makedirs(TICKET_DIR)
    if not os.path.exists(TICKET_FILE):
        logger.info("Unable to find ticket file")
        return {}

    try:
        with open(TICKET_FILE, 'r', encoding='utf-8') as file:
            return json.load(file)
    except json.JSONDecodeError:
        return {}

def save_tickets(ticket_data: dict):
    """
    Saves tickets to a JSON file.
    
    Args:
        ticket_data (dict): The ticket data to save.
    """
    previous_tickets = load_tickets()
    previous_tickets[ticket_data['ticket_id']] = ticket_data

    with open(TICKET_FILE, 'w', encoding='utf-8') as file:
        json.dump(previous_tickets, file, ensure_ascii=False, indent=2)

    return True
