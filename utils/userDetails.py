import json
import os
import logging
import os
import re
import uuid
from typing import Dict, List, Any

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel

# Load environment variables
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)


class UserDetailsResponse(BaseModel):
    """Response model for user details"""
    user_id: str
    profile: Dict[str, Any]  # Cleaned user profile data
    enrollment_summary: Dict[str, Any]  # Combined course and event summary
    course_enrollments: List[Dict[str, Any]]
    event_enrollments: List[Dict[str, Any]]
    is_authenticated: bool


class UserDetailsError(Exception):
    """Custom exception for user details operations"""
    pass


def is_uuid(value: str) -> bool:
    """
    Check if a string is a valid UUID.

    Args:
        value: String to check

    Returns:
        bool: True if the string is a valid UUID, False otherwise
    """
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, TypeError):
        return False


def is_masked_value(value: str) -> bool:
    """
    Check if a string appears to be a masked value (contains asterisks or similar masking patterns).

    Args:
        value: String to check

    Returns:
        bool: True if the string appears to be masked, False otherwise
    """
    if not isinstance(value, str):
        return False

    # Check for common masking patterns
    masking_patterns = [
        r'\*+',  # Multiple asterisks
        r'x{3,}',  # Multiple x's (case insensitive)
        r'X{3,}',  # Multiple X's
        r'##+',  # Multiple hash symbols
        r'-{3,}',  # Multiple dashes
        r'\.{3,}',  # Multiple dots
    ]

    for pattern in masking_patterns:
        if re.search(pattern, value):
            return True

    return False


def clean_user_data(user_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Remove masked, null, empty, and UUID fields from user data (except 'identifier').

    Args:
        user_data: Raw user data dictionary

    Returns:
        Dict: Cleaned user data
    """
    if not isinstance(user_data, dict):
        return {}

    cleaned_data = {}

    for key, value in user_data.items():
        # Skip null, empty string, empty list, or empty dict values
        if value in [None, '', [], {}]:
            continue

        # Keep 'identifier' field regardless of whether it's a UUID
        if key == 'identifier':
            cleaned_data[key] = value
            continue

        # Skip UUID fields (except identifier)
        if isinstance(value, str) and is_uuid(value):
            continue

        # Skip masked values
        if isinstance(value, str) and is_masked_value(value):
            continue

        # Handle nested dictionaries recursively
        if isinstance(value, dict):
            cleaned_nested = clean_user_data(value)
            if cleaned_nested:  # Only add if the cleaned dict is not empty
                cleaned_data[key] = cleaned_nested

        # Handle lists
        elif isinstance(value, list):
            cleaned_list = []
            for item in value:
                if isinstance(item, dict):
                    cleaned_item = clean_user_data(item)
                    if cleaned_item:  # Only add non-empty cleaned items
                        cleaned_list.append(cleaned_item)
                elif item not in [None, '', [], {}]:
                    # For non-dict items, apply the same filtering logic
                    if isinstance(item, str):
                        if not (is_uuid(item) or is_masked_value(item)):
                            cleaned_list.append(item)
                    else:
                        cleaned_list.append(item)

            if cleaned_list:  # Only add non-empty lists
                cleaned_data[key] = cleaned_list

        # For all other non-empty, non-null values
        else:
            cleaned_data[key] = value

    return cleaned_data


def clean_course_enrollment_data(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Transform course enrollment data to the expected output format.

    Args:
        data: List of course enrollment records

    Returns:
        List[Dict]: Transformed data with specified field mappings and null checks
    """
    # Handle empty or None data
    if not data or not isinstance(data, list):
        logger.info("No course enrollment data to clean")
        return []

    cleaned_data = []

    for course in data:
        if not isinstance(course, dict):
            continue

        # Create transformed course object
        transformed_course = {}

        # course_enrolment_date = enrolledDate
        if course.get('enrolledDate') is not None and course.get('enrolledDate') != '':
            transformed_course['course_enrolment_date'] = course['enrolledDate']

        # course_completion_percentage = completionPercentage
        if course.get('completionPercentage') is not None and course.get('completionPercentage') != '':
            transformed_course['course_completion_percentage'] = course['completionPercentage']
        else:
            transformed_course['course_completion_percentage'] = 0

        # Extract certificate information
        issued_certificates = course.get('issuedCertificates', [])
        if isinstance(issued_certificates, list) and len(issued_certificates) > 0:
            # Get the first certificate (assuming there's at least one)
            first_cert = issued_certificates[0]
            if isinstance(first_cert, dict):
                # certificate_id = issuedCertificates.token
                if first_cert.get('token') is not None and first_cert.get('token') != '':
                    transformed_course['course_issued_certificate_id'] = first_cert['token']

                # certificate_issued_on = issuedCertificates.lastIssuedOn
                if first_cert.get('lastIssuedOn') is not None and first_cert.get('lastIssuedOn') != '':
                    transformed_course['course_certificate_issued_on'] = first_cert['lastIssuedOn']

        content_obj = course.get('content', {})
        if isinstance(content_obj, dict):
            if content_obj.get('name') is not None and content_obj.get('name') != '':
                transformed_course['course_name'] = content_obj['name'].replace('\n', ' ').replace(':', ' ').replace('  ', ' ').strip()

            if content_obj.get('identifier') is not None and content_obj.get('identifier') != '':
                transformed_course['course_identifier'] = content_obj['identifier']

            # course_total_content_count = content.leafNodesCount
            if content_obj.get('leafNodesCount') is not None and content_obj.get('leafNodesCount') != '':
                transformed_course['course_total_content_count'] = content_obj['leafNodesCount']

        if course.get('courseId') is not None and course.get('courseId') != '':
            transformed_course['course_identifier'] = course['courseId']

        if course.get('batchId') is not None and course.get('batchId') != '':
            transformed_course['course_batch_id'] = course['batchId']

        # course_completed_on = completedOn
        if course.get('completedOn') is not None and course.get('completedOn') != '':
            transformed_course['course_last_accessed_on'] = course['completedOn']

        # Extract content status information
        content_status = course.get('contentStatus', [])
        if isinstance(content_status, list):
            # course_completed_contents_count = length of contentStatus array where count of values = 2
            completed_count = sum(1 for status in content_status if status == 2)
            if completed_count > 0:
                transformed_course['course_completed_content_count'] = completed_count

            # course_in-progress_contents_count = length of contentStatus array where count of values = 1
            in_progress_count = sum(1 for status in content_status if status == 1)
            if in_progress_count > 0:
                transformed_course['course_in-progress_content_count'] = in_progress_count

        # course_completion_status = status (set "not started" if value is 0, "in progress" if value is 1, "completed" if value is 2)
        if course.get('status') is not None:
            status_value = course['status']
            if status_value == 0:
                transformed_course['course_completion_status'] = 'not started'
            elif status_value == 1:
                transformed_course['course_completion_status'] = 'in progress'
            elif status_value == 2:
                transformed_course['course_completion_status'] = 'completed'

        # Only add the course if it has at least one field
        if transformed_course:
            cleaned_data.append(transformed_course)

    logger.info(f"Transformed {len(cleaned_data)} course enrollment records")
    return cleaned_data


def clean_event_enrollment_data(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Transform event enrollment data to the expected output format.

    Args:
        data: List of event enrollment records

    Returns:
        List[Dict]: Transformed data with specified field mappings and null checks
    """
    # Handle empty or None data
    if not data or not isinstance(data, list):
        logger.info("No event enrollment data to clean")
        return []

    cleaned_data = []

    for event_enrollment in data:
        if not isinstance(event_enrollment, dict):
            continue

        # Create transformed event object
        transformed_event = {}

        # event_enrolment_date = enrolledDate
        if event_enrollment.get('enrolledDate') is not None and event_enrollment.get('enrolledDate') != '':
            transformed_event['event_enrolment_date'] = event_enrollment['enrolledDate']

        # Extract event information
        event = event_enrollment.get('event', {})
        if isinstance(event, dict):
            # event_start_time = event.startDateTime
            if event.get('startDateTime') is not None and event.get('startDateTime') != '':
                transformed_event['event_start_time'] = event['startDateTime']

            # event_end_time = event.endDateTime
            if event.get('endDateTime') is not None and event.get('endDateTime') != '':
                transformed_event['event_end_time'] = event['endDateTime']

            # event_name = event.name
            if event.get('name') is not None and event.get('name') != '':
                transformed_event['event_name'] = event['name'].replace('\n', ' ').replace(':', ' ').replace('  ', ' ').strip()

            # event_identifier = event.identifier
            if event.get('identifier') is not None and event.get('identifier') != '':
                transformed_event['event_identifier'] = event['identifier']


        if event_enrollment.get('batchId') is not None and event_enrollment.get('batchId') != '':
            transformed_event['event_batch_id'] = event_enrollment['batchId']

        # Extract user event consumption information
        user_event_consumption = event_enrollment.get('userEventConsumption', [])
        if isinstance(user_event_consumption, list) and len(user_event_consumption) > 0:
            # Get the first certificate
            first_event = user_event_consumption[0]
            if isinstance(first_event, dict):
                # event_completion_percentage = userEventConsumption.completionPercentage
                if first_event.get('completionPercentage') is not None and first_event.get(
                        'completionPercentage') != '':
                    transformed_event['event_completion_percentage'] = first_event['completionPercentage']

                progress_details = first_event.get("progressdetails")
                if progress_details:
                    try:
                        details = json.loads(progress_details)
                        duration = details.get("duration")
                        transformed_event['event_consumption_time_in_minutes'] = duration
                    except Exception as e:
                        print("Error parsing progressdetails:", e)

        # Extract certificate information
        issued_certificates = event_enrollment.get('issuedCertificates', [])
        if isinstance(issued_certificates, list) and len(issued_certificates) > 0:
            # Get the first certificate
            first_cert = issued_certificates[0]
            if isinstance(first_cert, dict):
                # certificate_id = issuedCertificates[0].token
                if first_cert.get('token') is not None and first_cert.get('token') != '':
                    transformed_event['event_issued_certificate_id'] = first_cert['token']

                # certificate_issued_on = issuedCertificates[0].lastIssuedOn
                if first_cert.get('lastIssuedOn') is not None and first_cert.get('lastIssuedOn') != '':
                    transformed_event['event_certificate_issued_on'] = first_cert['lastIssuedOn']

        # event_completed_on = completedOn
        if event_enrollment.get('completedOn') is not None and event_enrollment.get('completedOn') != '':
            transformed_event['event_last_accessed_on'] = event_enrollment['completedOn']

        # event_completion_status = status (set "not started" if value is 0, "in progress" if value is 1, "completed" if value is 2)
        if event_enrollment.get('status') is not None:
            status_value = event_enrollment['status']
            if status_value == 0:
                transformed_event['event_completion_status'] = 'not started'
            elif status_value == 1:
                transformed_event['event_completion_status'] = 'in progress'
            elif status_value == 2:
                transformed_event['event_completion_status'] = 'completed'

        # Only add the event if it has at least one field
        if transformed_event:
            cleaned_data.append(transformed_event)

    logger.info(f"Transformed {len(cleaned_data)} event enrollment records")
    return cleaned_data


def course_enrollments_summary(user_course_enrollment_info: Dict[str, Any],
                               cleaned_course_enrollments: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Create a summary of course enrollments with key metrics.

    Args:
        user_course_enrollment_info: User course enrollment info containing karma points and time spent
        cleaned_course_enrollments: List of cleaned course enrollment records

    Returns:
        Dict: Summary with enrollment statistics and metrics
    """
    # Initialize summary object
    summary = {}

    # Extract karma points from userCourseEnrolmentInfo
    if isinstance(user_course_enrollment_info, dict):
        karma_points = user_course_enrollment_info.get('karmaPoints')
        if karma_points is not None and karma_points != '':
            summary['karma_points'] = karma_points

        # Extract time spent on completed courses
        time_spent = user_course_enrollment_info.get('timeSpentOnCompletedCourses')
        if time_spent is not None and time_spent != '':
            summary['time_spent_on_completed_courses_in_minutes'] = time_spent

    # Initialize counters
    not_started_count = 0
    in_progress_count = 0
    completed_count = 0
    certified_count = 0

    # Count courses by status and certificates
    if isinstance(cleaned_course_enrollments, list):
        for course in cleaned_course_enrollments:
            if isinstance(course, dict):
                # Count by completion status
                completion_status = course.get('course_completion_status', '').lower()
                if completion_status == 'not started':
                    not_started_count += 1
                elif completion_status == 'in progress':
                    in_progress_count += 1
                elif completion_status == 'completed':
                    completed_count += 1

                # Count certified courses
                if course.get('course_issued_certificate_id') is not None and course.get('course_issued_certificate_id') != '':
                    certified_count += 1

    # Add counts to summary (only if greater than 0)
    if not_started_count > 0:
        summary['total_courses_not_started'] = not_started_count

    if in_progress_count > 0:
        summary['total_courses_in_progress'] = in_progress_count

    if completed_count > 0:
        summary['total_courses_completed'] = completed_count

    if certified_count > 0:
        summary['certified_courses_count'] = certified_count

    logger.info(f"Course enrollment summary created: {len(summary)} metrics")
    logger.info(
        f"Courses - Not Started: {not_started_count}, In Progress: {in_progress_count}, Completed: {completed_count}, Certified: {certified_count}")

    return summary


def event_enrollments_summary(cleaned_event_enrollments: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Create a summary of event enrollments with key metrics.

    Args:
        cleaned_event_enrollments: List of cleaned event enrollment records

    Returns:
        Dict: Summary with event enrollment statistics and metrics
    """
    # Initialize summary object
    summary = {}

    # Initialize counters
    total_time_spent = 0
    not_started_count = 0
    in_progress_count = 0
    completed_count = 0
    certified_count = 0

    # Process each event enrollment
    if isinstance(cleaned_event_enrollments, list):
        for event in cleaned_event_enrollments:
            if isinstance(event, dict):
                # Sum up consumption time
                consumption_time = event.get('event_consumption_time_in_minutes')
                if consumption_time is not None and isinstance(consumption_time, (int, float)):
                    total_time_spent += consumption_time

                # Count by completion status
                completion_status = event.get('event_completion_status', '').lower()
                if completion_status == 'not started':
                    not_started_count += 1
                elif completion_status == 'in progress':
                    in_progress_count += 1
                elif completion_status == 'completed':
                    completed_count += 1

                # Count certified events
                if event.get('event_issued_certificate_id') is not None and event.get('event_issued_certificate_id') != '':
                    certified_count += 1

    # Add metrics to summary (only if greater than 0)
    if total_time_spent > 0:
        summary['time_spent_on_completed_events_in_minutes'] = total_time_spent

    if not_started_count > 0:
        summary['total_events_not_started'] = not_started_count

    if in_progress_count > 0:
        summary['total_events_in_progress'] = in_progress_count

    if completed_count > 0:
        summary['total_events_completed'] = completed_count

    if certified_count > 0:
        summary['certified_events_count'] = certified_count

    logger.info(f"Event enrollment summary created: {len(summary)} metrics")
    logger.info(
        f"Events - Not Started: {not_started_count}, In Progress: {in_progress_count}, Completed: {completed_count}, Certified: {certified_count}")
    logger.info(f"Total time spent on events: {total_time_spent} minutes")

    return summary

def merge_enrollment_info(main: dict, ext: dict) -> dict:
    merged = main.copy()
    for key, value in ext.items():
        if isinstance(value, (int, float)) and key in merged and isinstance(merged[key], (int, float)):
            merged[key] += value
        elif key not in merged:
            merged[key] = value
        # If key exists and is a dict (like 'addinfo'), you can decide to merge or keep main's value
    return merged


def create_combined_enrollment_summary(course_summary: Dict[str, Any], event_summary: Dict[str, Any]) -> Dict[str, Any]:
    """
    Combine course and event enrollment summaries into a single summary.

    Args:
        course_summary: Course enrollment summary
        event_summary: Event enrollment summary

    Returns:
        Dict: Combined enrollment summary
    """
    combined_summary = {}

    # Add all course summary fields
    if isinstance(course_summary, dict):
        combined_summary.update(course_summary)

    # Add all event summary fields
    if isinstance(event_summary, dict):
        combined_summary.update(event_summary)

    logger.info(f"Combined enrollment summary created with {len(combined_summary)} metrics")
    return combined_summary


class UserDetailsService:
    """Service class for handling user authentication and enrollment details"""

    def __init__(self):
        self.learning_service_url = os.getenv("learning_service_url")
        self.lms_service_url = os.getenv("lms_service_url")
        self.private_course_enrol_list_api = os.getenv("private_course_enrol_list_api")
        self.private_event_enrol_list_api = os.getenv("private_event_enrol_list_api")
        self.private_user_read_api = os.getenv("private_user_read_api")
        self.email_notification_api = os.getenv("email_notification_api")
        self.cert_issue_api = os.getenv("cert_issue_api")
        self.content_search_api = os.getenv("content_search_api")
        self.sb_cb_ext_service_url = os.getenv("sb_cb_ext_service_url")
        self.otp_generate_api = os.getenv("otp_generate_api")
        self.otp_verify_api = os.getenv("otp_verify_api")
        self.private_user_update_api = os.getenv("private_user_update_api")
        self.api_key = os.getenv("KARMAYOGI_API_KEY")

        if not self.api_key:
            logger.warning("KARMAYOGI_API_KEY not found in environment variables")

    async def get_user_details(self, user_id: str) -> UserDetailsResponse:
        """
        Main method to get user details and enrollment information.

        Args:
            user_id: The user ID

        Returns:
            UserDetailsResponse: Complete user details with combined enrollment summary

        Raises:
            UserDetailsError: If authentication fails or user ID doesn't match
        """
        try:
            logger.info(f"Fetching user details for user_id: {user_id}")

            # Step 1: Get user details and validate
            user_data = await self.fetch_user_details(user_id)

            # Step 3: Fetch enrollment details
            user_course_enrollment_info, course_enrollments = await self._fetch_course_enrollments(user_id)
            event_enrollments = await self._fetch_event_enrollments(user_id)

            print(f"get_user_details:: Fetched {len(course_enrollments)} course enrollments and {len(event_enrollments)} event enrollments")

            cleaned_course_enrollments = clean_course_enrollment_data(course_enrollments)
            cleaned_event_enrollments = clean_event_enrollment_data(event_enrollments)

            # Create individual summaries
            course_summary = course_enrollments_summary(user_course_enrollment_info, cleaned_course_enrollments)
            event_summary = event_enrollments_summary(cleaned_event_enrollments)

            # Combine summaries
            combined_enrollment_summary = create_combined_enrollment_summary(course_summary, event_summary)

            # Remove all null, empty string values and empty arrays from enrollment data
            updated_course_enrollments = [
                {k: v for k, v in course.items() if v not in [None, '', [], {}]}
                for course in cleaned_course_enrollments
            ]
            updated_event_enrollments = [
                {k: v for k, v in event.items() if v not in [None, '', [], {}]}
                for event in cleaned_event_enrollments
            ]

            return UserDetailsResponse(
                user_id=user_id,
                profile=user_data,
                enrollment_summary=combined_enrollment_summary,
                course_enrollments=updated_course_enrollments,
                event_enrollments=updated_event_enrollments,
                is_authenticated=True
            )

        except UserDetailsError:
            # Re-raise custom errors
            raise
        except Exception as e:
            logger.error(f"Unexpected error in get_user_details: {e}")
            raise UserDetailsError(f"Failed to fetch user details: {str(e)}")

    async def fetch_user_details(self, user_id: str) -> Dict[str, Any]:
        """
        Fetch user details from the API using cookie authentication and clean the response.

        Args:
            cookie: Authentication cookie

        Returns:
            Dict containing cleaned user details

        Raises:
            UserDetailsError: If API call fails
        """
        url = f"{self.learning_service_url}{self.private_user_read_api}{user_id}"
        headers = {
            "accept": "application/json, text/plain, */*",
            "Authorization": f"Bearer {self.api_key}",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                logger.info(f"Calling user details API: {url}")
                response = await client.get(url, headers=headers)

                if response.status_code == 200:
                    data = response.json()
                    raw_user_data = data.get("result", {}).get("response", {}) if "result" in data else data

                    # Clean the user data to remove masked, null, empty, and UUID fields
                    cleaned_user_data = clean_user_data(raw_user_data)

                    logger.info("User details fetched and cleaned successfully")
                    logger.info(
                        f"Original fields count: {len(raw_user_data) if isinstance(raw_user_data, dict) else 0}")
                    logger.info(f"Cleaned fields count: {len(cleaned_user_data)}")

                    return cleaned_user_data
                elif response.status_code == 401:
                    raise UserDetailsError("Authentication failed - invalid cookie")
                elif response.status_code == 403:
                    raise UserDetailsError("Access forbidden - insufficient permissions")
                else:
                    raise UserDetailsError(
                        f"User details API failed with status {response.status_code}: {response.text}")

        except httpx.TimeoutException:
            raise UserDetailsError("User details API request timed out")
        except httpx.RequestError as e:
            raise UserDetailsError(f"User details API request failed: {str(e)}")

    async def _fetch_course_enrollments(self, user_id: str) -> (Dict[str, Any], List[Dict[str, Any]]):
        """
        Fetch course enrollment details for the user.

        Args:
            user_id: The authenticated user ID

        Returns:
            Tuple of (user_course_enrollment_info, course_enrollments)
        """
        if not self.api_key:
            logger.warning("API key not available, skipping course enrollments")
            return ({}, [])

        url = f"{self.lms_service_url}{self.private_course_enrol_list_api}{user_id}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        # post request body
        requests_body = {
            "request": {
                "retiredCoursesEnabled": True,
                "status": ["In-Progress", "Completed"]
            }
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                logger.info(f"Calling course enrollment API: {url}")
                response = await client.post(url, headers=headers, json=requests_body)

                if response.status_code == 200:
                    data = response.json()
                    enrollments_result = data.get("result", {}) if "result" in data else data
                    enrollments = enrollments_result.get("courses", [])
                    ext_enrollments = enrollments_result.get("external_courses", [])
                    logger.info(f"Fetched {len(enrollments)} course enrollments")
                    user_course_enrollment_info = enrollments_result.get("userCourseEnrolmentInfo", {})
                    user_ext_course_enrollment_info = enrollments_result.get("userExternalCourseEnrolmentInfo", {})

                    # merge user_course_enrollment_info and user_ext_course_enrollment_info
                    merged_info = merge_enrollment_info(user_course_enrollment_info, user_ext_course_enrollment_info)

                    print(f"_fetch_course_enrollments:: enrollments BEFORE: {len(enrollments)}")
                    print(f"_fetch_course_enrollments:: ext_enrollments BEFORE: {len(ext_enrollments)}")

                    # add ext_enrollments to enrollments if they exist
                    if isinstance(ext_enrollments, list) and len(ext_enrollments) > 0:
                        enrollments.extend(ext_enrollments)

                    print(f"_fetch_course_enrollments:: enrollments AFTER: {len(enrollments)}")

                    return (merged_info, enrollments) if isinstance(enrollments, list) else ({}, [])
                elif response.status_code == 401:
                    logger.error("Course enrollment API: Authentication failed")
                    return ({}, [])
                else:
                    logger.error(f"Course enrollment API failed with status {response.status_code}")
                    return ({}, [])

        except httpx.TimeoutException:
            logger.error("Course enrollment API request timed out")
            return ({}, [])
        except httpx.RequestError as e:
            logger.error(f"Course enrollment API request failed: {str(e)}")
            return ({}, [])

    async def _fetch_event_enrollments(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Fetch event enrollment details for the user.

        Args:
            user_id: The authenticated user ID

        Returns:
            List of event enrollments
        """
        if not self.api_key:
            logger.warning("API key not available, skipping event enrollments")
            return []

        url = f"{self.lms_service_url}{self.private_event_enrol_list_api}{user_id}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                logger.info(f"Calling event enrollment API: {url}")
                response = await client.get(url, headers=headers)

                if response.status_code == 200:
                    data = response.json()
                    enrollments_result = data.get("result", {}) if "result" in data else data
                    enrollments = enrollments_result.get("events", [])
                    logger.info(f"Fetched {len(enrollments)} event enrollments")
                    return enrollments if isinstance(enrollments, list) else []
                elif response.status_code == 401:
                    logger.error("Event enrollment API: Authentication failed")
                    return []
                else:
                    logger.error(f"Event enrollment API failed with status {response.status_code}")
                    return []

        except httpx.TimeoutException:
            logger.error("Event enrollment API request timed out")
            return []
        except httpx.RequestError as e:
            logger.error(f"Event enrollment API request failed: {str(e)}")
            return []

    async def update_profile(self, user_id: str, profile_data: Dict[str, Any]) -> bool:
        """
        Update user profile with the provided data.

        Args:
            user_id: The user ID
            profile_data: Dictionary containing profile fields to update

        Returns:
            bool: True if update was successful, False otherwise

        Raises:
            UserDetailsError: If API call fails
        """
        if not self.api_key:
            logger.warning("API key not available, skipping profile update")
            return False

        url = f"{self.learning_service_url}{self.private_user_update_api}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        print(f"update_profile:: profile_data: {profile_data}")

        # if profile_data contains profileDetails.professionalDetails[0].verifiedKarmayogi and if it is not String, convert it to String
        if 'profileDetails' in profile_data and 'professionalDetails' in profile_data['profileDetails']:
            professional_details = profile_data['profileDetails']['professionalDetails']
            if isinstance(professional_details, list) and len(professional_details) > 0:
                if 'verifiedKarmayogi' in professional_details[0]:
                    verified_karmayogi = professional_details[0].get('verifiedKarmayogi')
                    if verified_karmayogi is not None and not isinstance(verified_karmayogi, str):
                        professional_details[0]['verifiedKarmayogi'] = str(verified_karmayogi)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                logger.info(f"Calling user profile update API: {url}")
                response = await client.patch(url, headers=headers, json=profile_data)

                if response.status_code == 200:
                    logger.info("User profile updated successfully")
                    return True
                elif response.status_code == 401:
                    raise UserDetailsError("Authentication failed - invalid API key")
                else:
                    raise UserDetailsError(
                        f"Profile update API failed with status {response.status_code}: {response.text}")

        except httpx.TimeoutException:
            raise UserDetailsError("Profile update API request timed out")
        except httpx.RequestError as e:
            raise UserDetailsError(f"Profile update API request failed: {str(e)}")

    async def otp_generate(self, phone: str) -> bool:
        """
        Generate OTP for the user.

        Args:
            user_id: User ID to generate OTP for
            phone: Phone number to send OTP to

        Returns:
            bool: True if OTP generation was successful, False otherwise
        """
        # Code to invoke the OTP generation API
        service = UserDetailsService()
        if not service.api_key:
            logger.warning("API key not available, skipping OTP generation")
            return False
        url = f"{service.sb_cb_ext_service_url}{service.otp_generate_api}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {service.api_key}"
        }
        requests_body = {
            "request": {
                "type": "phone",
                "key": phone
            }
        }
        print(f"otp_generate:: requests_body: {requests_body}")
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                logger.info(f"Calling OTP generation API: {url}")
                response = await client.post(url, headers=headers, json=requests_body)

                if response.status_code == 200:
                    logger.info("OTP generated successfully")
                    return True
                elif response.status_code == 401:
                    raise UserDetailsError("Authentication failed - invalid API key")
                else:
                    raise UserDetailsError(
                        f"OTP generation API failed with status {response.status_code}: {response.text}")

        except httpx.TimeoutException:
            raise UserDetailsError("OTP generation API request timed out")
        except httpx.RequestError as e:
            raise UserDetailsError(f"OTP generation API request failed: {str(e)}")

    async def otp_verify(self, phone: str, otp: str) -> bool:
        """
        Verify the OTP for the user.

        Args:
            phone: Phone number to verify OTP for
            otp: OTP to verify

        Returns:
            bool: True if OTP verification was successful, False otherwise
        """
        # Code to invoke the OTP verification API
        service = UserDetailsService()
        if not service.api_key:
            logger.warning("API key not available, skipping OTP verification")
            return False
        url = f"{service.sb_cb_ext_service_url}{service.otp_verify_api}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {service.api_key}"
        }
        requests_body = {
            "request": {
                "type": "phone",
                "key": phone,
                "otp": otp
            }
        }
        print(f"otp_verify:: requests_body: {requests_body}")
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                logger.info(f"Calling OTP verification API: {url}")
                response = await client.post(url, headers=headers, json=requests_body)

                if response.status_code == 200:
                    logger.info("OTP verified successfully")
                    return True
                elif response.status_code == 401:
                    raise UserDetailsError("Authentication failed - invalid API key")
                else:
                    raise UserDetailsError(
                        f"OTP verification API failed with status {response.status_code}: {response.text}")

        except httpx.TimeoutException:
            raise UserDetailsError("OTP verification API request timed out")
        except httpx.RequestError as e:
            raise UserDetailsError(f"OTP verification API request failed: {str(e)}")


service = UserDetailsService()
# Convenience function for easy import and usage
async def get_user_details(user_id: str) -> UserDetailsResponse:
    return await service.get_user_details(user_id)

async def get_user_profile(user_id: str) -> Dict[str, Any]:
    return await service.fetch_user_details(user_id)

async def update_user_profile(user_id: str, email: str = None, phone: str = None, name: str = None) -> bool:
    """
    Update user profile with provided parameters

    Args:
        user_id: User ID to update
        email: New email address (optional)
        phone: New phone number (optional)
        name: New name (optional)

    Returns:
        bool: True if successful, False otherwise
    """

    try:
        # Get current user details
        user_details = await service.get_user_details(user_id)
        user_data = user_details.profile

        # Build the update payload
        profile_data = {
            "request": {
                "userId": user_id
            }
        }

        # Handle email update
        if email:
            profile_data["request"]["email"] = email

            # Build profileDetails structure
            profile_details = user_data.get('profileDetails', {})
            personal_details = profile_details.get('personalDetails', {})

            # Update email in personalDetails
            personal_details['primaryEmail'] = email
            personal_details['officialEmail'] = email

            profile_details['personalDetails'] = personal_details
            profile_data["request"]["profileDetails"] = profile_details

        # Handle phone update
        if phone:
            profile_data["request"]["phone"] = phone

            # Build profileDetails structure if not already built
            if "profileDetails" not in profile_data["request"]:
                profile_details = user_data.get('profileDetails', {})
                personal_details = profile_details.get('personalDetails', {})
                profile_data["request"]["profileDetails"] = profile_details

            # Update phone in personalDetails
            profile_data["request"]["profileDetails"]["personalDetails"]["mobile"] = phone

        # Handle name update
        if name:
            profile_data["request"]["firstname"] = name
            profile_data["request"]["lastname"] = None  # Set lastname to None as per API spec

            # Build profileDetails structure if not already built
            if "profileDetails" not in profile_data["request"]:
                profile_details = user_data.get('profileDetails', {})
                personal_details = profile_details.get('personalDetails', {})
                profile_data["request"]["profileDetails"] = profile_details

            # Update name in personalDetails
            profile_data["request"]["profileDetails"]["personalDetails"]["firstname"] = name

        # Call the update API
        return await service.update_profile(user_id, profile_data)

    except Exception as e:
        logger.error(f"Error updating user profile: {e}")
        return False

async def generate_otp(phone: str) -> bool:
    """
    Generate OTP for the user.

    Args:
        phone: Phone number to send OTP to

    Returns:
        bool: True if OTP generation was successful, False otherwise
    """
    print("userDetails::generate_otp:: phone: ", phone)
    return await service.otp_generate(phone)
    # return True

async def verify_otp(phone: str, otp: str) -> bool:
    """
    Verify the OTP for the user.

    Args:
        phone: Phone number to verify OTP for
        otp: OTP to verify

    Returns:
        bool: True if OTP verification was successful, False otherwise
    """
    print("userDetails::verify_otp:: phone: ", phone, " otp: ", otp)
    return await service.otp_verify(phone, otp)
    # return True