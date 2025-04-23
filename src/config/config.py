"""API configuration and constants"""

import os
from dotenv import load_dotenv

load_dotenv()

KB_BASE_URL = os.getenv("KB_BASE_URL")

API_ENDPOINTS = {
    "CERTIFICATE": f"{KB_BASE_URL}/course/batch/cert/v1/issue",
    "EMAIL": f"{KB_BASE_URL}/user/v1/notification/email",
    "CONTENT_SEARCH": f"{KB_BASE_URL}/content/v1/search",
    "ENROLL": f"{KB_BASE_URL}/course/private/v3/user/enrollment/list",
    "USER_SEARCH": f"{KB_BASE_URL}/private/user/v1/search" 
}

LLM_CONFIG = {
    'temperature' : 1,
    'top_p' : 0.9,
    'top_k' : 40,
    'max_output_tokens' : 4096,
    'response_mime_type' : 'text/plain'

}

REQUEST_TIMEOUT = 60

TICKET_DIR = os.path.join(os.path.dirname(__file__), "../../data/tickets")
TICKET_FILE = os.path.join(TICKET_DIR, "tickets.json")
