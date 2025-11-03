"""
Course Module Status API Client

This module provides async API client for fetching detailed course module status
for the Karmayogi Bharat platform. Uses httpx for production-ready async HTTP calls.
"""

import asyncio
import logging
import os
from typing import Dict, List, Optional, Set
from dataclasses import dataclass
import httpx
from dotenv import load_dotenv

# Load environment variables if not already loaded
load_dotenv()

logger = logging.getLogger(__name__)


@dataclass
class ModuleInfo:
    """Represents detailed information about a course module"""
    identifier: str
    name: str
    status: int  # 0=Not Started, 1=In Progress, 2=Completed
    status_text: str
    object_type: str = "Unknown"


class CourseModuleStatusAPI:
    """
    Production-ready API client for fetching course module status
    
    Features:
    - Async/await with httpx for concurrent requests
    - Connection pooling for 1000+ concurrent users
    - Automatic retry logic
    - Timeout handling
    - Thread-safe (no shared state)
    """
    
    # Load configuration from environment
    BASE_URL = os.getenv("KARMAYOGI_PORTAL_BASE_URL", "https://portal.igotkarmayogi.gov.in")
    
    # API endpoints - loaded from environment with defaults
    ENROLLMENT_ENDPOINT = os.getenv("COURSE_ENROLLMENT_API", "/api/course/private/v4/user/enrollment/list/{user_id}")
    CONTENT_READ_ENDPOINT = os.getenv("COURSE_CONTENT_READ_API", "/api/content/v2/read/{course_id}")
    CONTENT_SEARCH_ENDPOINT = os.getenv("COURSE_CONTENT_SEARCH_API", "/api/content/v1/search")
    
    # Auth token from environment
    _api_key = os.getenv("KARMAYOGI_API_KEY")
    if not _api_key:
        logger.warning("KARMAYOGI_API_KEY not found in environment variables")
    AUTH_TOKEN = f"Bearer {_api_key}" if _api_key else None
    
    def __init__(self, timeout: int = 30, max_retries: int = 3):
        """
        Initialize API client with connection pooling
        
        Args:
            timeout: Request timeout in seconds
            max_retries: Number of retry attempts for failed requests
        """
        self.timeout = timeout
        self.max_retries = max_retries
        
        # httpx.AsyncClient with connection pooling for production
        # This allows handling 1000+ concurrent users efficiently
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            limits=httpx.Limits(
                max_keepalive_connections=100,
                max_connections=500,
                keepalive_expiry=30.0
            ),
            follow_redirects=True
        )
    
    async def close(self):
        """Close the HTTP client and cleanup connections"""
        await self.client.aclose()
    
    async def __aenter__(self):
        """Async context manager entry"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()
    
    async def _make_request(
        self,
        method: str,
        url: str,
        headers: Optional[Dict] = None,
        json: Optional[Dict] = None,
        params: Optional[Dict] = None
    ) -> Optional[Dict]:
        """
        Make HTTP request with retry logic
        
        Args:
            method: HTTP method (GET, POST, etc.)
            url: Full URL
            headers: Request headers
            json: JSON payload for POST requests
            params: Query parameters
            
        Returns:
            Response JSON or None on failure
        """
        for attempt in range(self.max_retries):
            try:
                response = await self.client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json,
                    params=params
                )
                
                response.raise_for_status()
                return response.json()
                
            except httpx.TimeoutException:
                logger.warning(f"Request timeout (attempt {attempt + 1}/{self.max_retries}): {url}")
                if attempt == self.max_retries - 1:
                    logger.error(f"Request failed after {self.max_retries} attempts: {url}")
                    return None
                await asyncio.sleep(1 * (attempt + 1))  # Exponential backoff
                
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error {e.response.status_code}: {url}")
                return None
                
            except Exception as e:
                logger.error(f"Unexpected error during request: {e}")
                return None
        
        return None
    
    async def fetch_user_enrollment_details(self, user_id: str, course_id: str) -> Optional[Dict]:
        """
        Fetch user enrollment details including langContentStatus
        
        Args:
            user_id: User ID
            course_id: Course ID
            
        Returns:
            Enrollment data or None on failure
        """
        url = f"{self.BASE_URL}{self.ENROLLMENT_ENDPOINT.format(user_id=user_id)}"
        
        headers = {
            "Authorization": self.AUTH_TOKEN,
            "Content-Type": "application/json"
        }
        
        payload = {
            "request": {
                "retiredCoursesEnabled": True,
                "courseId": [course_id]
            }
        }
        
        logger.info(f"Fetching enrollment details for user={user_id}, course={course_id}")
        
        data = await self._make_request("POST", url, headers=headers, json=payload)
        
        if not data or data.get('responseCode') != 'OK':
            logger.error(f"Failed to fetch enrollment details: {data}")
            return None
        
        courses = data.get('result', {}).get('courses', [])
        if not courses:
            logger.warning(f"No enrollment found for user={user_id}, course={course_id}")
            return None
        
        course_data = courses[0]
        
        return {
            'lang_content_status': course_data.get('langContentStatus', {}),
            'completion_percentage': float(course_data.get('completionPercentage', 0)),
            'leaf_nodes_count': int(course_data.get('leafNodesCount', 0)),
            'course_name': course_data.get('courseName', 'Unknown'),
            'enrolled_date': course_data.get('enrolledDate'),
            'batch_id': course_data.get('batchId'),
            'language': course_data.get('content', {}).get('language', ['English'])[0]
        }
    
    async def fetch_course_structure(self, course_id: str) -> Optional[Dict]:
        """
        Fetch complete course structure including all leafNodes
        
        Args:
            course_id: Course ID
            
        Returns:
            Course structure data or None on failure
        """
        url = f"{self.BASE_URL}{self.CONTENT_READ_ENDPOINT.format(course_id=course_id)}"
        
        headers = {
            "Content-Type": "application/json"
        }
        
        logger.info(f"Fetching course structure for course={course_id}")
        
        data = await self._make_request("GET", url, headers=headers)
        
        if not data or data.get('responseCode') != 'OK':
            logger.error(f"Failed to fetch course structure: {data}")
            return None
        
        content = data.get('result', {}).get('content', {})
        
        return {
            'leaf_nodes': content.get('leafNodes', []),
            'child_nodes': content.get('childNodes', []),
            'course_name': content.get('name', 'Unknown'),
            'leaf_nodes_count': int(content.get('leafNodesCount', 0))
        }
    
    async def fetch_module_names(self, module_ids: List[str]) -> Dict[str, Dict]:
        """
        Fetch human-readable names for module IDs
        
        Args:
            module_ids: List of module identifiers
            
        Returns:
            Dictionary mapping module_id to module info
        """
        if not module_ids:
            return {}
        
        url = f"{self.BASE_URL}{self.CONTENT_SEARCH_ENDPOINT}"
        
        headers = {
            "Content-Type": "application/json"
        }
        
        payload = {
            "request": {
                "filters": {
                    "identifier": module_ids
                },
                "isSecureSettingsDisabled": True,
                "sort_by": {
                    "createdOn": "desc"
                },
                "fields": ["identifier", "name", "endDate", "startDate", "status", "versionKey", "createdOn"],
                "facets": ["status"],
                "limit": 1000
            }
        }
        
        logger.info(f"Fetching module names for {len(module_ids)} modules")
        
        data = await self._make_request("POST", url, headers=headers, json=payload)
        
        if not data or data.get('responseCode') != 'OK':
            logger.error(f"Failed to fetch module names: {data}")
            return {}
        
        result = data.get('result', {})
        modules = {}
        
        # Combine content from different types (Content, QuestionSet, etc.)
        for item in result.get('content', []):
            modules[item['identifier']] = {
                'name': item.get('name', 'Unknown'),
                'object_type': item.get('objectType', 'Content'),
                'status': item.get('status', 'Unknown')
            }
        
        for item in result.get('QuestionSet', []):
            modules[item['identifier']] = {
                'name': item.get('name', 'Unknown'),
                'object_type': item.get('objectType', 'QuestionSet'),
                'status': item.get('status', 'Unknown')
            }
        
        logger.info(f"Retrieved names for {len(modules)} modules")
        
        return modules
    
    async def get_detailed_module_status(
        self,
        user_id: str,
        course_id: str
    ) -> Optional[Dict]:
        """
        Get complete module status breakdown for a user's course
        
        This is the main method that orchestrates all API calls and calculates
        the delta between enrolled modules and course structure.
        
        Args:
            user_id: User ID
            course_id: Course ID
            
        Returns:
            Detailed module status breakdown or None on failure
        """
        try:
            logger.info(f"Getting detailed module status for user={user_id}, course={course_id}")
            
            # Step 1: Fetch enrollment details (langContentStatus)
            enrollment_data = await self.fetch_user_enrollment_details(user_id, course_id)
            if not enrollment_data:
                return None
            
            # Step 2: Fetch course structure (leafNodes)
            course_structure = await self.fetch_course_structure(course_id)
            if not course_structure:
                return None
            
            # Step 3: Fetch module names
            all_module_ids = course_structure['leaf_nodes']
            module_names = await self.fetch_module_names(all_module_ids)
            
            # Step 4: Calculate delta
            module_status = self._calculate_module_status(
                enrollment_data['lang_content_status'],
                course_structure['leaf_nodes'],
                module_names
            )
            
            # Build result
            result = {
                'success': True,
                'user_id': user_id,
                'course_id': course_id,
                'course_name': enrollment_data['course_name'],
                'completion_percentage': enrollment_data['completion_percentage'],
                'total_modules': enrollment_data['leaf_nodes_count'],
                'batch_id': enrollment_data['batch_id'],
                'language': enrollment_data['language'],
                'module_breakdown': {
                    'not_started': {
                        'count': len(module_status['not_started']),
                        'modules': [
                            {
                                'id': m.identifier,
                                'name': m.name,
                                'type': m.object_type
                            }
                            for m in module_status['not_started']
                        ]
                    },
                    'in_progress': {
                        'count': len(module_status['in_progress']),
                        'modules': [
                            {
                                'id': m.identifier,
                                'name': m.name,
                                'type': m.object_type
                            }
                            for m in module_status['in_progress']
                        ]
                    },
                    'completed': {
                        'count': len(module_status['completed']),
                        'modules': [
                            {
                                'id': m.identifier,
                                'name': m.name,
                                'type': m.object_type
                            }
                            for m in module_status['completed']
                        ]
                    }
                }
            }
            
            logger.info(f"Module status calculated: {result['module_breakdown']['not_started']['count']} not started, "
                       f"{result['module_breakdown']['in_progress']['count']} in progress, "
                       f"{result['module_breakdown']['completed']['count']} completed")
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting detailed module status: {e}", exc_info=True)
            return None
    
    def _calculate_module_status(
        self,
        lang_content_status: Dict,
        leaf_nodes: List[str],
        module_names: Dict[str, Dict]
    ) -> Dict[str, List[ModuleInfo]]:
        """
        Calculate delta between leafNodes and langContentStatus
        
        Args:
            lang_content_status: Tracked modules from enrollment API
            leaf_nodes: All modules from course structure API
            module_names: Module metadata from search API
            
        Returns:
            Categorized module status
        """
        # Get the language key (usually 'english')
        language_key = list(lang_content_status.keys())[0] if lang_content_status else None
        tracked_modules = lang_content_status.get(language_key, {}) if language_key else {}
        
        # Create sets for comparison
        tracked_module_ids: Set[str] = set(tracked_modules.keys())
        all_module_ids: Set[str] = set(leaf_nodes)
        
        # Calculate not started (in leafNodes but not in langContentStatus)
        not_started_ids: Set[str] = all_module_ids - tracked_module_ids
        
        # Categorize tracked modules
        in_progress_ids: Set[str] = {mid for mid, status in tracked_modules.items() if status == 1}
        completed_ids: Set[str] = {mid for mid, status in tracked_modules.items() if status == 2}
        
        # Build result with detailed module information
        result = {
            'not_started': [],
            'in_progress': [],
            'completed': []
        }
        
        # Not started modules
        for module_id in not_started_ids:
            module_info = module_names.get(module_id, {})
            result['not_started'].append(ModuleInfo(
                identifier=module_id,
                name=module_info.get('name', 'Unknown Module'),
                status=0,
                status_text="Not Started",
                object_type=module_info.get('object_type', 'Unknown')
            ))
        
        # In progress modules
        for module_id in in_progress_ids:
            module_info = module_names.get(module_id, {})
            result['in_progress'].append(ModuleInfo(
                identifier=module_id,
                name=module_info.get('name', 'Unknown Module'),
                status=1,
                status_text="In Progress",
                object_type=module_info.get('object_type', 'Unknown')
            ))
        
        # Completed modules
        for module_id in completed_ids:
            module_info = module_names.get(module_id, {})
            result['completed'].append(ModuleInfo(
                identifier=module_id,
                name=module_info.get('name', 'Unknown Module'),
                status=2,
                status_text="Completed",
                object_type=module_info.get('object_type', 'Unknown')
            ))
        
        return result


# Singleton instance for reuse across requests
_api_client: Optional[CourseModuleStatusAPI] = None


async def get_module_status_api_client() -> CourseModuleStatusAPI:
    """
    Get or create singleton API client instance
    
    This ensures connection pooling is shared across all requests
    for optimal performance with 1000+ concurrent users.
    """
    global _api_client
    
    if _api_client is None:
        _api_client = CourseModuleStatusAPI(timeout=30, max_retries=3)
        logger.info("Created new CourseModuleStatusAPI client with connection pooling")
    
    return _api_client


async def cleanup_module_status_api_client():
    """Cleanup the singleton API client on shutdown"""
    global _api_client
    
    if _api_client:
        await _api_client.close()
        _api_client = None
        logger.info("Cleaned up CourseModuleStatusAPI client")
