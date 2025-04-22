"""API configuration and constants"""

BASE_URL = "https://portal.uat.karmayogibharat.net/api"

API_ENDPOINTS = {
    "CERTIFICATE": f"{BASE_URL}/course/batch/cert/v1/issue",
    "EMAIL": f"{BASE_URL}/user/v1/notification/email",
    "CONTENT_SEARCH": f"{BASE_URL}/content/v1/search",
    "ENROLL": f"{BASE_URL}/course/private/v3/user/enrollment/list",
    "USER_SEARCH": f"{BASE_URL}/user/v1/search" 
}

DEFAULT_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json"
}

REQUEST_TIMEOUT = 60

AUTH_CONFIG = {
    "AUTH_URL": f"{BASE_URL}/auth/realms/sunbird/protocol/openid-connect/token",
    "CLIENT_ID": "admin-cli"
}
