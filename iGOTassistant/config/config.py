"""API configuration and constants"""

import os
from dotenv import load_dotenv

load_dotenv()


KB_BASE_URL = os.getenv("KB_BASE_URL")
USE_ADK = True

ZOHO_URI = "https://desk.zoho.in/api/v1/tickets"

API_ENDPOINTS = {
    "CERTIFICATE": f"{os.getenv('lms_service_url')}{os.getenv('cert_issue_api')}",
    "EMAIL": f"{os.getenv('learning_service_url')}{os.getenv('email_notification_api')}",
    "CONTENT_SEARCH": f"{os.getenv('knowledge_mw_service_url')}{os.getenv('content_search_api')}",
    "ENROLL": f"{os.getenv('lms_service_url')}{os.getenv('private_course_enrol_list')}",
    "OTP": f"{os.getenv('sb_cb_ext_service_url')}{os.getenv('otp_generate_api')}",
    "UPDATE": f"{os.getenv('learning_service_url')}{os.getenv('private_user_update_api')}",
    "PROFILE": f"{os.getenv('learning_service_url')}{os.getenv('private_user_read_api')}"
}




 


# API_ENDPOINTS = {
#     "CERTIFICATE": f"{KB_BASE_URL}/api/course/batch/cert/v1/issue",
#     "EMAIL": f"{KB_BASE_URL}/api/user/v1/notification/email",
#     "CONTENT_SEARCH": f"{KB_BASE_URL}/api/content/v1/search",
#     "ENROLL": f"{KB_BASE_URL}/api/course/private/v3/user/enrollment/list",
#     "USER_READ": f"{KB_BASE_URL}/api/private/user/v1/read",
#     "OTP": f"{KB_BASE_URL}/api/otp/v1/generate",
#     "UPDATE": f"{KB_BASE_URL}/api/user/private/v1/update",
#     "PROFILE": f"{KB_BASE_URL}/api/user/private/v1/read/",
#     "PROXIES" : f"{KB_BASE_URL}/apis/proxies/v8/api/user/v2/read"
# }

LLM_CONFIG = {
    # 'temperature': 0.7,  # Reduced for faster, more consistent responses
    'temperature': 0.3,  # Reduced for faster, more consistent responses
    # 'top_p': 0.8,  # Optimized for speed vs creativity balance
    'top_p': 0.7,  # Optimized for speed vs creativity balance
    # 'top_k': 20,  # Reduced for faster token selection
    'top_k': 10,  # Reduced for faster token selection
    # 'max_output_tokens': 2048,  # Reduced for faster generation
    'max_output_tokens': 1024,  # Reduced for faster generation
    'response_mime_type': 'text/plain',
    # Additional performance optimizations
    'candidate_count': 1,  # Single response for speed
    'stop_sequences': [],  # No stop sequences for faster completion
    'safety_settings': [],  # Disable safety checks for speed (if acceptable)
}

GOOGLE_AGENT = True
# GOOGLE_AGENT = False

REQUEST_TIMEOUT = 60

TICKET_DIR = os.path.join(os.path.dirname(__file__), "../../data/tickets")
TICKET_FILE = os.path.join(TICKET_DIR, "tickets.json")
