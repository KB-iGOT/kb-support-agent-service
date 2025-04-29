"""API configuration and constants"""

import os
from dotenv import load_dotenv

load_dotenv()

KB_BASE_URL = os.getenv("KB_BASE_URL")
USE_ADK = True 

API_ENDPOINTS = {
    "CERTIFICATE": f"{KB_BASE_URL}/api/course/batch/cert/v1/issue",
    "EMAIL": f"{KB_BASE_URL}/api/user/v1/notification/email",
    "CONTENT_SEARCH": f"{KB_BASE_URL}/api/content/v1/search",
    "ENROLL": f"{KB_BASE_URL}/api/course/private/v3/user/enrollment/list",
    "USER_SEARCH": f"{KB_BASE_URL}/api/private/user/v1/search",
    "OTP": f"{KB_BASE_URL}/api/otp/v1/generate",
    "UPDATE": f"{KB_BASE_URL}/api/user/private/v1/update",
    "PROFILE": f"{KB_BASE_URL}/api/user/private/v1/read/"
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
