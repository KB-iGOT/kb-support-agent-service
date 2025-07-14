import copy
import os
import logging
import re
import uuid
from typing import Dict, Optional, List, Any
import httpx
from pydantic import BaseModel
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from ..config.config import API_ENDPOINTS

# Configure logging
logger = logging.getLogger(__name__)


class UserDetailsResponse(BaseModel):
    """Response model for user details"""
    user_id: str
    enrollment_summary: Dict[str, Any]
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

        # Extract batch information
        batch = course.get('batch', {})
        if isinstance(batch, dict):
            # batch_end_date = batch.endDate
            if batch.get('endDate') is not None and batch.get('endDate') != '':
                transformed_course['batch_end_date'] = batch['endDate']

            # batch_enrollment_end_date = batch.enrollmentEndDate
            if batch.get('enrollmentEndDate') is not None and batch.get('enrollmentEndDate') != '':
                transformed_course['batch_enrollment_end_date'] = batch['enrollmentEndDate']

            # batch_startDate = batch.startDate
            if batch.get('startDate') is not None and batch.get('startDate') != '':
                transformed_course['batch_startDate'] = batch['startDate']

            # batch_status = batch.status (active if value is 1 else in-active)
            if batch.get('status') is not None:
                batch_status_value = batch['status']
                if batch_status_value == 1:
                    transformed_course['batch_status'] = 'active'
                else:
                    transformed_course['batch_status'] = 'in-active'

        # course_completion_percentage = completionPercentage
        if course.get('completionPercentage') is not None and course.get('completionPercentage') != '':
            transformed_course['course_completion_percentage'] = course['completionPercentage']

        # Extract certificate information
        issued_certificates = course.get('issuedCertificates', [])
        if isinstance(issued_certificates, list) and len(issued_certificates) > 0:
            # Get the first certificate (assuming there's at least one)
            first_cert = issued_certificates[0]
            if isinstance(first_cert, dict):
                # certificate_id = issuedCertificates.token
                if first_cert.get('token') is not None and first_cert.get('token') != '':
                    transformed_course['issued_certificate_id'] = first_cert['token']

                # certificate_issued_on = issuedCertificates.lastIssuedOn
                if first_cert.get('lastIssuedOn') is not None and first_cert.get('lastIssuedOn') != '':
                    transformed_course['certificate_issued_on'] = first_cert['lastIssuedOn']

        # course_name = courseName
        if course.get('courseName') is not None and course.get('courseName') != '':
            transformed_course['course_name'] = course['courseName']

        # course_completed_on = completedOn
        if course.get('completedOn') is not None and course.get('completedOn') != '':
            transformed_course['course_completed_on'] = course['completedOn']

        # course_total_contents_count = leafNodesCount
        if course.get('leafNodesCount') is not None and course.get('leafNodesCount') != '':
            transformed_course['course_total_content_count'] = course['leafNodesCount']

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
                transformed_event['event_name'] = event['name']

        # Extract user event consumption information
        user_event_consumption = event_enrollment.get('userEventConsumption', {})
        if isinstance(user_event_consumption, dict):
            # event_completion_percentage = userEventConsumption.completionPercentage
            if user_event_consumption.get('completionPercentage') is not None and user_event_consumption.get(
                    'completionPercentage') != '':
                transformed_event['event_completion_percentage'] = user_event_consumption['completionPercentage']

            # event_consumption_time_in_minutes = userEventConsumption.progressdetails.duration
            progress_details = user_event_consumption.get('progressdetails', {})
            if isinstance(progress_details, dict):
                duration = progress_details.get('duration')
                if duration is not None and duration != '':
                    transformed_event['event_consumption_time_in_minutes'] = duration

        # Extract certificate information
        issued_certificates = event_enrollment.get('issuedCertificates', [])
        if isinstance(issued_certificates, list) and len(issued_certificates) > 0:
            # Get the first certificate
            first_cert = issued_certificates[0]
            if isinstance(first_cert, dict):
                # certificate_id = issuedCertificates[0].token
                if first_cert.get('token') is not None and first_cert.get('token') != '':
                    transformed_event['issued_certificate_id'] = first_cert['token']

                # certificate_issued_on = issuedCertificates[0].lastIssuedOn
                if first_cert.get('lastIssuedOn') is not None and first_cert.get('lastIssuedOn') != '':
                    transformed_event['certificate_issued_on'] = first_cert['lastIssuedOn']

        # event_completed_on = completedOn
        if event_enrollment.get('completedOn') is not None and event_enrollment.get('completedOn') != '':
            transformed_event['event_completed_on'] = event_enrollment['completedOn']

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
                if course.get('issued_certificate_id') is not None and course.get('issued_certificate_id') != '':
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
                if event.get('issued_certificate_id') is not None and event.get('issued_certificate_id') != '':
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
        self.base_url = "https://portal.uat.karmayogibharat.net"
        self.api_key = os.getenv("KARMAYOGI_API_KEY")

        if not self.api_key:
            logger.warning("KARMAYOGI_API_KEY not found in environment variables")

    async def get_user_details(self, user_id: str) -> UserDetailsResponse:
        """
        Main method to get user details and enrollment information.

        Args:
            user_id: The user ID to validate against

        Returns:
            UserDetailsResponse: Complete user details with combined enrollment

        Raises:
            UserDetailsError: If authentication fails or user ID doesn't match
        """
        try:
            logger.info(f"Fetching user details for user_id: {user_id}")

            # Step 1: Get user details and validate
            user_data = await self._fetch_user_details(user_id)
            actual_user_id = user_data.get("identifier")

            if not actual_user_id:
                raise UserDetailsError("User ID not found in API response")

            # Step 2: Compare user IDs
            if actual_user_id != user_id:
                logger.error(f"User ID mismatch: provided={user_id}, actual={actual_user_id}")
                raise UserDetailsError(
                    f"User ID mismatch: provided {user_id} doesn't match authenticated user {actual_user_id}")

            logger.info(f"User ID validation successful for: {user_id}")

            # Step 3: Fetch enrollment details
            user_course_enrollment_info, course_enrollments = await self._fetch_course_enrollments(actual_user_id)
            event_enrollments = await self._fetch_event_enrollments(actual_user_id)

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
                user_id=actual_user_id,
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

    async def _fetch_user_details(self, user_id: str) -> Dict[str, Any]:
        """
        Fetch user details from the API using KB_AUTH_TOKEN authentication and clean the response.

        Args:
            user_id: User ID to fetch details for

        Returns:
            Dict containing cleaned user details

        Raises:
            UserDetailsError: If API call fails
        """
        # url = f"{self.base_url}/apis/proxies/v8/api/user/v2/read/{user_id}"
        url = API_ENDPOINTS['PROFILE'] + user_id
        headers = {
            "accept": "application/json, text/plain, */*",
            "Authorization": f"Bearer {os.getenv('KB_AUTH_TOKEN')}"
        }

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                logger.info(f"Calling user details API: {url}")
                response = await client.get(url, headers=headers)

                if response.status_code == 200:
                    data = response.json()
                    raw_user_data = data.get("result", {}).get("response", {}) if "result" in data else data

                    print("RAW_USER_DATA", raw_user_data)

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

    async def _fetch_course_enrollments(self, user_id: str) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
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

        url = f"{self.base_url}/api/course/private/v3/user/enrollment/list/{user_id}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.getenv('KB_AUTH_TOKEN')}"
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                logger.info(f"Calling course enrollment API: {url}")
                response = await client.get(url, headers=headers)

                if response.status_code == 200:
                    data = response.json()
                    enrollments_result = data.get("result", {}) if "result" in data else data
                    enrollments = enrollments_result.get("courses", [])
                    logger.info(f"Fetched {len(enrollments)} course enrollments")
                    user_course_enrollment_info = enrollments_result.get("userCourseEnrolmentInfo", {})
                    return (user_course_enrollment_info, enrollments) if isinstance(enrollments, list) else ({}, [])
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
        # if not self.api_key:
        #     logger.warning("API key not available, skipping event enrollments")
        #     return []

        url = f"{self.base_url}/api/user/private/v1/events/list/{user_id}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.getenv('KB_AUTH_TOKEN')}"
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


# Convenience function for easy import and usage
async def get_user_details(user_id: str ) -> UserDetailsResponse:
    """
    Convenience function to get user details and enrollment information.

    Args:
        user_id: The user ID to validate against
        cookie: The authentication cookie

    Returns:
        UserDetailsResponse: Complete user details with enrollments

    Raises:
        UserDetailsError: If authentication fails or user ID doesn't match
    """
    service = UserDetailsService()
    return await service.get_user_details(user_id)


# Helper function to check if user is authenticated
async def verify_user_authentication(user_id: str) -> bool:
    """
    Quick verification if user is authenticated and user_id matches.

    Args:
        user_id: The user ID to validate

    Returns:
        bool: True if authenticated and user_id matches, False otherwise
    """
    try:
        result = await get_user_details(user_id)
        return result.is_authenticated
    except UserDetailsError:
        return False
    except Exception:
        return False


# Helper function to get enrollment summary
async def get_enrollment_summary(user_id: str) -> Dict[str, Any]:
    """
    Get a summary of user's enrollments.

    Args:
        user_id: The user ID

    Returns:
        Dict with enrollment summary
    """
    try:
        result = await get_user_details(user_id)
        return {
            "user_id": result.user_id,
            "is_authenticated": result.is_authenticated,
            "enrollment_summary": result.enrollment_summary
        }
    except UserDetailsError as e:
        return {
            "user_id": user_id,
            "is_authenticated": False,
            "error": str(e),
            "enrollment_summary": {}
        }


# def clean_course_enrollment_data(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
#     """
#     Remove unwanted fields from each enrollment record in the courses list,
#     but extract and keep specific batch fields at the course level.

#     Args:
#         data: List of course enrollment records

#     Returns:
#         List[Dict]: Cleaned data with unwanted fields removed and batch fields extracted
#     """
#     # Handle empty or None data
#     if not data or not isinstance(data, list):
#         logger.info("No course enrollment data to clean")
#         return []

#     # Fields to remove from each course enrollment record (excluding batch since we'll handle it separately)
#     unwanted_fields = {
#         'description',
#         'courseLogoUrl',
#         'content',
#         'oldEnrolledDate',
#         'addedBy',
#         'userId',
#         'certificates'
#     }

#     # Batch fields to extract and keep
#     batch_fields_to_keep = {
#         'startDate',
#         'endDate',
#         'name',
#         'enrollmentEndDate',
#         'status'
#     }

#     # Create a deep copy to avoid modifying the original data
#     cleaned_data = copy.deepcopy(data)

#     # Clean each course enrollment record
#     for course in cleaned_data:
#         if isinstance(course, dict):
#             # Extract batch fields if batch exists
#             if 'batch' in course and isinstance(course['batch'], dict):
#                 batch_data = course['batch']

#                 # Add batch fields to the course level with 'batch.' prefix
#                 for field in batch_fields_to_keep:
#                     if field in batch_data:
#                         course[f'batch.{field}'] = batch_data[field]

#             # Remove the original batch object
#             course.pop('batch', None)

#             # Remove other unwanted fields if they exist
#             for field in unwanted_fields:
#                 course.pop(field, None)  # pop with None default to avoid KeyError

#     logger.info(f"Cleaned {len(cleaned_data)} course enrollment records")
#     logger.info(f"Removed fields: {', '.join(sorted(unwanted_fields | {'batch'}))}")
#     logger.info(f"Extracted batch fields: {', '.join(f'batch.{field}' for field in sorted(batch_fields_to_keep))}")

#     return cleaned_data


# def clean_event_enrollment_data(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
#     """
#     Remove unwanted fields from each enrollment record in the events list.

#     Args:
#         data: List of event enrollment records

#     Returns:
#         List[Dict]: Cleaned data with unwanted fields removed from events
#     """
#     # Handle empty or None data
#     if not data or not isinstance(data, list):
#         logger.info("No event enrollment data to clean")
#         return []

#     # Fields to remove from each event enrollment record
#     unwanted_event_fields = {
#         'oldEnrolledDate',
#         'event',
#         'addedBy',
#         'contentId',
#         'contextid',
#         'batchId',
#         'progress',
#         'certificates',
#         'certstatus'
#     }

#     # Fields to remove from batchDetails array items
#     unwanted_batch_fields = {
#         'eventid',
#         'oldUpdatedDate',
#         'certTemplates',
#         'batch_location_details',
#         'enableqr',
#         'description',
#         'oldCreatedDate',
#         'updatedDate',
#         'tandc',
#         'oldEndDate',
#         'createdBy',
#         'mentors',
#         'oldEnrollmentEndDate',
#         'oldStartDate'
#     }

#     # Create a deep copy to avoid modifying the original data
#     cleaned_data = copy.deepcopy(data)

#     # Clean each event enrollment record
#     for event in cleaned_data:
#         if isinstance(event, dict):
#             # Remove unwanted event-level fields
#             for field in unwanted_event_fields:
#                 event.pop(field, None)  # pop with None default to avoid KeyError

#             # Clean batchDetails if it exists
#             if 'batchDetails' in event and isinstance(event['batchDetails'], list):
#                 for batch_detail in event['batchDetails']:
#                     if isinstance(batch_detail, dict):
#                         # Remove unwanted batch detail fields
#                         for field in unwanted_batch_fields:
#                             batch_detail.pop(field, None)

#     logger.info(f"Cleaned {len(cleaned_data)} event enrollment records")
#     logger.info(f"Removed event fields: {', '.join(sorted(unwanted_event_fields))}")
#     logger.info(f"Removed batch detail fields: {', '.join(sorted(unwanted_batch_fields))}")

#     return cleaned_data

