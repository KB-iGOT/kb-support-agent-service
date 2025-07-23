# utils/zoho_utils.py
"""
Zoho Desk Utility Module

This module provides comprehensive utilities for interacting with Zoho Desk API including:
- OAuth token management
- Ticket creation and management
- Contact management
- Search functionality
- Error handling and logging

Features:
- Automatic token refresh
- Retry mechanisms
- Comprehensive error handling
- Multiple ticket templates
- Contact creation/update
- Ticket status tracking

Required Environment Variables:
- ZOHO_REFRESH_TOKEN: Zoho OAuth refresh token for API access
- ZOHO_CLIENT_ID: Zoho OAuth client ID
- ZOHO_CLIENT_SECRET: Zoho OAuth client secret
- ZOHO_ORG_ID: Zoho Desk organization ID (default: 60023043070)
- ZOHO_DEPARTMENT_ID: Zoho Desk department ID (default: 120349000000010772)
- ZOHO_BASE_URL: Zoho Desk base URL (default: https://desk.zoho.in/api/v1)

Usage:
    from utils.zoho_utils import ZohoDesk

    zoho = ZohoDesk()
    ticket_id = await zoho.create_certificate_issue_ticket(
        user_name="John Doe",
        user_email="john@example.com",
        user_mobile="1234567890",
        course_name="Python Basics",
        issue_type="not_received"
    )
"""

import json
import logging
import os
import time
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
from dataclasses import dataclass
import httpx

logger = logging.getLogger(__name__)


class ZohoTicketPriority(Enum):
    """Zoho Desk ticket priorities"""
    LOW = "P4"
    MEDIUM = "P3"
    HIGH = "P2"
    URGENT = "P1"


class ZohoTicketStatus(Enum):
    """Zoho Desk ticket statuses"""
    OPEN = "Open"
    IN_PROGRESS = "In Progress"
    WAITING_FOR_CUSTOMER = "Waiting for Customer"
    ESCALATED = "Escalated"
    CLOSED = "Closed"


class ZohoIssueCategory(Enum):
    """Common issue categories for Karmayogi platform"""
    CERTIFICATE_ISSUES = "Certificate Issues"
    PROFILE_ISSUES = "Profile Issues"
    COURSE_ACCESS = "Course Access"
    TECHNICAL_SUPPORT = "Technical Support"
    GENERAL_INQUIRY = "General Inquiry"
    PLATFORM_BUG = "Platform Bug"


@dataclass
class ZohoTicketData:
    """Data structure for Zoho ticket creation"""
    subject: str
    description: str
    user_name: str
    user_email: str
    user_mobile: str
    priority: ZohoTicketPriority = ZohoTicketPriority.MEDIUM
    category: ZohoIssueCategory = ZohoIssueCategory.GENERAL_INQUIRY
    issue_type: str = ""
    course_name: str = ""
    additional_info: Dict[str, Any] = None


@dataclass
class ZohoTicketResponse:
    """Response structure from Zoho ticket creation"""
    success: bool
    ticket_id: str = ""
    ticket_number: str = ""
    error_message: str = ""
    raw_response: Dict = None


class ZohoDesk:
    """
    Comprehensive Zoho Desk API client for Karmayogi platform
    """

    def __init__(self):
        self.base_url = os.getenv('ZOHO_BASE_URL', 'https://desk.zoho.in/api/v1')
        self.org_id = os.getenv('ZOHO_ORG_ID', '60023043070')
        self.department_id = os.getenv('ZOHO_DEPARTMENT_ID', '120349000000010772')
        self.department_name = os.getenv('ZOHO_DEPARTMENT_NAME', 'Karmayogi Bharat')

        # OAuth credentials
        self.refresh_token = os.getenv('ZOHO_REFRESH_TOKEN')
        self.client_id = os.getenv('ZOHO_CLIENT_ID')
        self.client_secret = os.getenv('ZOHO_CLIENT_SECRET')

        # Token management
        self._access_token = None
        self._token_expiry = 0

        # Validate configuration
        self._validate_config()

    def _validate_config(self):
        """Validate required configuration"""
        required_vars = ['ZOHO_REFRESH_TOKEN', 'ZOHO_CLIENT_ID', 'ZOHO_CLIENT_SECRET']
        missing_vars = [var for var in required_vars if not os.getenv(var)]

        if missing_vars:
            logger.error(f"Missing required Zoho configuration: {', '.join(missing_vars)}")
            raise ValueError(f"Missing Zoho configuration: {', '.join(missing_vars)}")

    async def get_access_token(self, force_refresh: bool = False) -> Optional[str]:
        """
        Get Zoho access token with automatic refresh

        Args:
            force_refresh: Force token refresh even if current token is valid

        Returns:
            Access token string or None if failed
        """
        try:
            # Check if current token is still valid
            if not force_refresh and self._access_token and time.time() < self._token_expiry:
                return self._access_token

            logger.info("Refreshing Zoho access token")

            url = "https://accounts.zoho.in/oauth/v2/token"
            params = {
                'refresh_token': self.refresh_token,
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'scope': 'Desk.tickets.ALL,Desk.contacts.READ,Desk.contacts.WRITE,Desk.search.READ',
                'grant_type': 'refresh_token'
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, params=params)

                if response.status_code == 200:
                    token_data = response.json()
                    self._access_token = token_data.get('access_token')
                    expires_in = token_data.get('expires_in', 3600)
                    self._token_expiry = time.time() + expires_in - 300  # 5 min buffer

                    logger.info("Successfully obtained Zoho access token")
                    return self._access_token
                else:
                    logger.error(f"Failed to get Zoho access token: {response.status_code} - {response.text}")
                    return None

        except Exception as e:
            logger.error(f"Error getting Zoho access token: {e}")
            return None

    async def _make_api_request(self, method: str, endpoint: str, data: Dict = None,
                                params: Dict = None, retry_count: int = 3) -> Tuple[bool, Dict]:
        """
        Make authenticated API request to Zoho Desk with retry logic

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint (e.g., 'tickets')
            data: Request payload for POST/PUT
            params: Query parameters
            retry_count: Number of retry attempts

        Returns:
            Tuple of (success: bool, response_data: dict)
        """
        for attempt in range(retry_count):
            try:
                access_token = await self.get_access_token()
                if not access_token:
                    return False, {"error": "Failed to obtain access token"}

                url = f"{self.base_url}/{endpoint}"
                headers = {
                    "orgId": self.org_id,
                    "Authorization": f"Zoho-oauthtoken {access_token}",
                    "Content-Type": "application/json"
                }

                async with httpx.AsyncClient(timeout=60.0) as client:
                    if method.upper() == 'GET':
                        response = await client.get(url, headers=headers, params=params)
                    elif method.upper() == 'POST':
                        response = await client.post(url, headers=headers, json=data, params=params)
                    elif method.upper() == 'PUT':
                        response = await client.put(url, headers=headers, json=data, params=params)
                    elif method.upper() == 'DELETE':
                        response = await client.delete(url, headers=headers, params=params)
                    else:
                        return False, {"error": f"Unsupported HTTP method: {method}"}

                    if response.status_code in [200, 201]:
                        return True, response.json()
                    elif response.status_code == 401 and attempt < retry_count - 1:
                        # Token might be expired, refresh and retry
                        logger.warning("Access token expired, refreshing...")
                        await self.get_access_token(force_refresh=True)
                        continue
                    else:
                        logger.error(f"Zoho API request failed: {response.status_code} - {response.text}")
                        return False, {
                            "error": f"API request failed with status {response.status_code}",
                            "details": response.text
                        }

            except Exception as e:
                logger.error(f"Error making Zoho API request (attempt {attempt + 1}): {e}")
                if attempt == retry_count - 1:
                    return False, {"error": str(e)}

        return False, {"error": "Max retry attempts exceeded"}

    def _split_name(self, full_name: str) -> Tuple[str, str]:
        """Split full name into first and last name"""
        if not full_name:
            return "", ""

        name_parts = full_name.strip().split(' ', 1)
        first_name = name_parts[0] if name_parts else ""
        last_name = name_parts[1] if len(name_parts) > 1 else ""

        return first_name, last_name

    async def create_ticket(self, ticket_data: ZohoTicketData) -> ZohoTicketResponse:
        """
        Create a ticket in Zoho Desk

        Args:
            ticket_data: ZohoTicketData object with ticket information

        Returns:
            ZohoTicketResponse object with creation result
        """
        try:
            logger.info(f"Creating Zoho ticket: {ticket_data.subject}")

            first_name, last_name = self._split_name(ticket_data.user_name)

            # Prepare custom fields
            custom_fields = {
                "cf_jira_id": None,
                "cf_categories": ticket_data.category.value,
                "cf_name": ticket_data.user_name,
                "cf_current_designation": None,
                "cf_ministry_state": None,
                "cf_checkbox_1": "false",
                "cf_department_name": None,
                "cf_working_team": None,
                "cf_closed_fate": None,
                "cf_cadre_of_the_employee": None,
                "cf_checkbox": "false",
                "cf_categories_1": None,
                "cf_message": ticket_data.course_name if ticket_data.course_name else None,
                "cf_severity": "Sev 3",
                "cf_modules_type": ticket_data.category.value,
                "cf_sub_categories": ticket_data.issue_type,
                "cf_organization": None,
                "cf_attachment": None,
                "cf_source": "Bot",
                "cf_requestor": ticket_data.user_name,
                "cf_do_not_merge": "false",
                "cf_sub_cadre_of_the_employee": None
            }

            # Add additional custom fields if provided
            if ticket_data.additional_info:
                custom_fields.update(ticket_data.additional_info)

            payload = {
                "entitySkills": [],
                "subCategory": "",
                "cf": custom_fields,
                "productId": "",
                "contact": {
                    "firstName": first_name,
                    "lastName": last_name,
                    "email": ticket_data.user_email,
                    "phone": ticket_data.user_mobile
                },
                "subject": ticket_data.subject,
                "dueDate": None,
                "departmentId": self.department_id,
                "department": {
                    "id": self.department_id,
                    "name": self.department_name
                },
                "channel": "Bot",
                "description": ticket_data.description,
                "language": "English",
                "priority": ticket_data.priority.value,
                "classification": "",
                "phone": ticket_data.user_mobile,
                "category": ticket_data.category.value,
                "email": ticket_data.user_email,
                "status": ZohoTicketStatus.OPEN.value
            }

            success, response_data = await self._make_api_request('POST', 'tickets', data=payload)

            if success:
                ticket_id = response_data.get('id', '')
                ticket_number = response_data.get('ticketNumber', '')

                logger.info(f"Successfully created Zoho ticket - ID: {ticket_id}, Number: {ticket_number}")

                return ZohoTicketResponse(
                    success=True,
                    ticket_id=str(ticket_id),
                    ticket_number=str(ticket_number),
                    raw_response=response_data
                )
            else:
                logger.error(f"Failed to create Zoho ticket: {response_data}")
                return ZohoTicketResponse(
                    success=False,
                    error_message=response_data.get('error', 'Unknown error'),
                    raw_response=response_data
                )

        except Exception as e:
            logger.error(f"Error creating Zoho ticket: {e}")
            return ZohoTicketResponse(
                success=False,
                error_message=str(e)
            )

    async def create_certificate_issue_ticket(self, user_name: str, user_email: str, user_mobile: str,
                                              course_name: str, issue_type: str) -> ZohoTicketResponse:
        """
        Create a certificate-specific issue ticket

        Args:
            user_name: User's full name
            user_email: User's email address
            user_mobile: User's mobile number
            course_name: Name of the course
            issue_type: Type of certificate issue (incorrect_name, not_received, qr_missing)

        Returns:
            ZohoTicketResponse object
        """
        # Generate issue-specific content
        issue_title = issue_type.replace('_', ' ').title()

        if issue_type == "incorrect_name":
            subject = f"[IGOT KARMAYOGI ASSISTANT] Certificate Name Correction - {course_name}"
            description = f"""Certificate Name Correction Request

User Details:
- Name: {user_name}  
- Email: {user_email}
- Mobile: {user_mobile}

Issue Details:
- Course: {course_name}
- Issue: Incorrect name on certificate
- Description: User {user_name} reported that their name is incorrect on the certificate for the course '{course_name}'. Please verify the user's profile information and reissue the certificate with the correct name.

Next Steps:
1. Verify user's correct name in profile
2. Check certificate details
3. Reissue certificate with correct name
4. Notify user once completed

Priority: This affects the user's ability to use their certificate for official purposes."""

        elif issue_type == "not_received":
            subject = f"[IGOT KARMAYOGI ASSISTANT] Certificate Not Received - {course_name}"
            description = f"""Certificate Not Received Request

User Details:
- Name: {user_name}
- Email: {user_email}
- Mobile: {user_mobile}

Issue Details:
- Course: {course_name}
- Issue: Certificate not received after course completion
- Description: User {user_name} completed the course '{course_name}' but has not received their certificate. Please verify completion status and issue the certificate.

Next Steps:
1. Verify course completion status
2. Check certificate generation process
3. Issue/reissue certificate
4. Notify user once completed

Priority: User has completed the course and should receive their earned certificate."""

        elif issue_type == "qr_missing":
            subject = f"[IGOT KARMAYOGI ASSISTANT] Certificate QR Code Issue - {course_name}"
            description = f"""Certificate QR Code Missing Request

User Details:
- Name: {user_name}
- Email: {user_email}
- Mobile: {user_mobile}

Issue Details:
- Course: {course_name}
- Issue: QR code missing from certificate
- Description: User {user_name} received their certificate for '{course_name}' but the QR code is missing. Please reissue the certificate with a proper QR code.

Next Steps:
1. Check current certificate format
2. Regenerate certificate with QR code
3. Replace existing certificate
4. Notify user once completed

Priority: QR code is required for certificate verification."""

        else:
            subject = f"[IGOT KARMAYOGI ASSISTANT] Certificate Issue - {course_name}"
            description = f"""General Certificate Issue

User Details:
- Name: {user_name}
- Email: {user_email}
- Mobile: {user_mobile}

Issue Details:
- Course: {course_name}
- Issue Type: {issue_title}
- Description: User {user_name} reported a certificate-related issue with the course '{course_name}'. Please investigate and resolve the issue.

Next Steps:
1. Contact user for more details if needed
2. Investigate the specific issue
3. Provide appropriate resolution
4. Notify user once completed"""

        ticket_data = ZohoTicketData(
            subject=subject,
            description=description,
            user_name=user_name,
            user_email=user_email,
            user_mobile=user_mobile,
            priority=ZohoTicketPriority.MEDIUM,
            category=ZohoIssueCategory.CERTIFICATE_ISSUES,
            issue_type=issue_title,
            course_name=course_name
        )

        return await self.create_ticket(ticket_data)

    async def create_profile_issue_ticket(self, user_name: str, user_email: str, user_mobile: str,
                                          issue_description: str,
                                          issue_type: str = "profile_update") -> ZohoTicketResponse:
        """
        Create a profile-related issue ticket

        Args:
            user_name: User's full name
            user_email: User's email address
            user_mobile: User's mobile number
            issue_description: Detailed description of the profile issue
            issue_type: Type of profile issue

        Returns:
            ZohoTicketResponse object
        """
        subject = f"[IGOT KARMAYOGI ASSISTANT] Profile Issue - {user_name}"

        description = f"""Profile Issue Request

User Details:
- Name: {user_name}
- Email: {user_email}
- Mobile: {user_mobile}

Issue Details:
- Issue Type: {issue_type.replace('_', ' ').title()}
- Description: {issue_description}

Next Steps:
1. Review user's profile information
2. Investigate the reported issue
3. Provide appropriate resolution
4. Notify user once completed

This ticket was created through the Karmayogi Bharat AI Assistant."""

        ticket_data = ZohoTicketData(
            subject=subject,
            description=description,
            user_name=user_name,
            user_email=user_email,
            user_mobile=user_mobile,
            priority=ZohoTicketPriority.MEDIUM,
            category=ZohoIssueCategory.PROFILE_ISSUES,
            issue_type=issue_type.replace('_', ' ').title()
        )

        return await self.create_ticket(ticket_data)

    async def create_technical_support_ticket(self, user_name: str, user_email: str, user_mobile: str,
                                              issue_description: str, platform_section: str = "") -> ZohoTicketResponse:
        """
        Create a technical support ticket

        Args:
            user_name: User's full name
            user_email: User's email address
            user_mobile: User's mobile number
            issue_description: Detailed description of the technical issue
            platform_section: Specific section/feature where issue occurred

        Returns:
            ZohoTicketResponse object
        """
        subject = f"[IGOT KARMAYOGI ASSISTANT] Technical Support - {platform_section if platform_section else 'Platform Issue'}"

        description = f"""Technical Support Request

User Details:
- Name: {user_name}
- Email: {user_email}
- Mobile: {user_mobile}

Issue Details:
- Platform Section: {platform_section if platform_section else 'General'}
- Issue Description: {issue_description}

Next Steps:
1. Investigate the technical issue
2. Reproduce the problem if possible
3. Implement fix or provide workaround
4. Notify user once resolved

This ticket was created through the Karmayogi Bharat AI Assistant."""

        ticket_data = ZohoTicketData(
            subject=subject,
            description=description,
            user_name=user_name,
            user_email=user_email,
            user_mobile=user_mobile,
            priority=ZohoTicketPriority.HIGH if "error" in issue_description.lower() or "crash" in issue_description.lower() else ZohoTicketPriority.MEDIUM,
            category=ZohoIssueCategory.TECHNICAL_SUPPORT,
            issue_type="Technical Issue"
        )

        return await self.create_ticket(ticket_data)

    async def get_ticket(self, ticket_id: str) -> Tuple[bool, Dict]:
        """
        Get ticket details by ID

        Args:
            ticket_id: Zoho ticket ID

        Returns:
            Tuple of (success: bool, ticket_data: dict)
        """
        return await self._make_api_request('GET', f'tickets/{ticket_id}')

    async def update_ticket(self, ticket_id: str, update_data: Dict) -> Tuple[bool, Dict]:
        """
        Update ticket information

        Args:
            ticket_id: Zoho ticket ID
            update_data: Dictionary of fields to update

        Returns:
            Tuple of (success: bool, response_data: dict)
        """
        return await self._make_api_request('PUT', f'tickets/{ticket_id}', data=update_data)

    async def search_tickets(self, search_query: str, limit: int = 50) -> Tuple[bool, Dict]:
        """
        Search tickets by query

        Args:
            search_query: Search query string
            limit: Maximum number of results

        Returns:
            Tuple of (success: bool, search_results: dict)
        """
        params = {
            'query': search_query,
            'limit': limit
        }
        return await self._make_api_request('GET', 'search/tickets', params=params)

    async def add_ticket_comment(self, ticket_id: str, comment: str, is_public: bool = True) -> Tuple[bool, Dict]:
        """
        Add comment to ticket

        Args:
            ticket_id: Zoho ticket ID
            comment: Comment text
            is_public: Whether comment is visible to customer

        Returns:
            Tuple of (success: bool, response_data: dict)
        """
        comment_data = {
            "content": comment,
            "isPublic": is_public,
            "contentType": "plainText"
        }
        return await self._make_api_request('POST', f'tickets/{ticket_id}/comments', data=comment_data)

    async def get_user_tickets(self, user_email: str, status: str = None, limit: int = 50) -> Tuple[bool, Dict]:
        """
        Get tickets for a specific user

        Args:
            user_email: User's email address
            status: Optional status filter
            limit: Maximum number of results

        Returns:
            Tuple of (success: bool, tickets_data: dict)
        """
        search_query = f"email:{user_email}"
        if status:
            search_query += f" AND status:{status}"

        return await self.search_tickets(search_query, limit)

    async def health_check(self) -> Dict[str, Any]:
        """
        Check Zoho Desk service health

        Returns:
            Health check results
        """
        try:
            access_token = await self.get_access_token()
            if not access_token:
                return {
                    "status": "unhealthy",
                    "error": "Failed to obtain access token",
                    "zoho_desk": "unavailable"
                }

            # Test API connection by getting organization info
            success, response = await self._make_api_request('GET', 'organizations')

            if success:
                return {
                    "status": "healthy",
                    "zoho_desk": "connected",
                    "organization": response.get('name', 'Unknown'),
                    "token_valid": True
                }
            else:
                return {
                    "status": "unhealthy",
                    "error": response.get('error', 'API request failed'),
                    "zoho_desk": "connection_failed"
                }

        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "zoho_desk": "exception"
            }


# Global instance for easy importing
zoho_desk = ZohoDesk()