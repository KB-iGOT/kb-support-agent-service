import json
import logging
import os
from typing import Dict, Optional, Any, List

from dotenv import load_dotenv
# Use the new Google Gen AI SDK instead of deprecated vertexai.caching
from google import genai
from google.genai.types import CreateCachedContentConfig, Content, Part, HttpOptions
from google.auth import default
from google.oauth2 import service_account

# from .utils.contentCache import hash_cookie
# from .utils.userDetails import get_user_details, UserDetailsError

from .contentCache import hash_cookie
from .userDetails import get_user_details, UserDetailsError

logger = logging.getLogger(__name__)

load_dotenv()


class VertexContentCache:
    """
    Vertex AI Content Caching implementation using Google Gen AI SDK.

    This creates cached content in Vertex AI that contains user's enrollment details,
    reducing token costs for subsequent LLM calls by caching the user context.
    """

    def __init__(self, project_id: str, location: str = "us-central1", credentials_path: Optional[str] = None):
        self.project_id = project_id
        self.location = location
        self.model_name = "gemini-2.0-flash-001"  # Use stable model name

        # Validate inputs
        if not project_id:
            raise ValueError("project_id cannot be empty")
        if not location:
            raise ValueError("location cannot be empty")

        logger.info(f"Initializing VertexContentCache with project: {project_id}, location: {location}")

        # Set up credentials - for service accounts, we don't need to specify scopes
        # Service accounts use IAM roles instead of OAuth scopes
        credentials = None
        if credentials_path and os.path.exists(credentials_path):
            # Use explicit service account credentials
            credentials = service_account.Credentials.from_service_account_file(credentials_path)
            logger.info(f"Using service account credentials from: {credentials_path}")
            logger.info(f"Service account email: {credentials.service_account_email}")
        elif os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            # Use credentials from environment variable
            cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            if os.path.exists(cred_path):
                credentials = service_account.Credentials.from_service_account_file(cred_path)
                logger.info(f"Using service account credentials from environment: {cred_path}")
                logger.info(f"Service account email: {credentials.service_account_email}")
        else:
            # Try to use Application Default Credentials with required scopes
            try:
                credentials, _ = default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
                logger.info("Using Application Default Credentials")
            except Exception as e:
                logger.error(f"Failed to load credentials: {e}")
                raise

        # Initialize Google Gen AI client with Vertex AI configuration
        try:
            # First, let's try without explicit credentials to see if ADC works
            self.client = genai.Client(
                vertexai=True,
                project=project_id,
                location=location,
                http_options=HttpOptions(api_version="v1")
            )

            logger.info(f"Successfully initialized Vertex AI client for project: {project_id}, location: {location}")
            logger.info("Skipping client test - will validate during actual usage")

        except Exception as e:
            logger.error(f"Failed to initialize Vertex AI client: {e}")
            raise

        # Track cached content by user
        self._user_cache_registry: Dict[str, str] = {}  # user_key -> cached_content_name

    def _generate_user_cache_key(self, user_id: str, cookie_hash: str) -> str:
        """Generate unique cache key for user"""
        return f"{user_id}:{cookie_hash[:16]}"

    async def get_or_create_cached_content(self, user_id: str, cookie: str, force_refresh: bool = False) -> Optional[
        str]:
        """
        Get existing cached content or create new one for user details.

        Args:
            user_id: User identifier
            cookie: Authentication cookie
            force_refresh: Force recreation of cached content

        Returns:
            Cached content name that can be used with GenerativeModel, or None if failed
        """
        try:
            cookie_hash = hash_cookie(cookie)
            user_cache_key = self._generate_user_cache_key(user_id, cookie_hash)

            # Check if we already have cached content for this user
            if not force_refresh and user_cache_key in self._user_cache_registry:
                cached_content_name = self._user_cache_registry[user_cache_key]

                # TODO: Add cache expiration check here if needed
                logger.info(f"Using existing cached content for user {user_id}: {cached_content_name}")
                return cached_content_name

            # Fetch fresh user details
            logger.info(f"Fetching user details for caching: {user_id}")
            user_details = await get_user_details(user_id, cookie)

            if not user_details:
                logger.error(f"No user details found for user {user_id}")
                return None

            formatted_content = json.dumps(user_details.model_dump(), indent=2, ensure_ascii=False)

            # Create system instruction content
            system_instruction = Content(
                parts=[
                    Part(text="""You are a helpful customer support agent for Karmayogi Bharat platform. 
                    Use the cached user context to provide personalized assistance about their courses, events, and learning progress.
                    Always be polite, empathetic, and provide accurate information based on their enrollment data.""")
                ]
            )

            # Create user context content
            user_context_content = Content(
                parts=[Part(text=formatted_content)],
                role="user"
            )

            # Create cached content configuration
            config = CreateCachedContentConfig(
                display_name=f"karmayogi_user_{user_id}_{cookie_hash[:8]}",
                system_instruction=system_instruction,
                contents=[user_context_content],
                ttl="7200s"  # 2 hours in seconds
            )

            # Create cached content using Google Gen AI SDK
            logger.info(f"Creating cached content for user {user_id}")
            cached_content = self.client.caches.create(
                model=self.model_name,
                config=config
            )

            # Store in our registry
            self._user_cache_registry[user_cache_key] = cached_content.name

            logger.info(f"Successfully created cached content: {cached_content.name}")
            return cached_content.name

        except UserDetailsError as e:
            logger.error(f"Failed to fetch user details for caching: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to create cached content for user {user_id}: {e}")
            return None

    def get_model_with_cached_content(self, cached_content_name: str) -> Optional[str]:
        """
        Return the cached content name to be used with generate_content.

        Note: With Google Gen AI SDK, we don't get a separate model instance,
        instead we use the cached_content parameter in generate_content calls.

        Args:
            cached_content_name: Name of the cached content

        Returns:
            Cached content name to use in generate_content calls
        """
        try:
            # With the new SDK, we just return the cached content name
            # to be used in generate_content calls
            return cached_content_name
        except Exception as e:
            logger.error(f"Failed to validate cached content {cached_content_name}: {e}")
            return None

    async def invalidate_user_cache(self, user_id: str, cookie_hash: str) -> bool:
        """
        Invalidate (delete) cached content for a specific user.

        Args:
            user_id: User identifier
            cookie_hash: Hashed cookie

        Returns:
            True if cache was invalidated, False otherwise
        """
        try:
            user_cache_key = self._generate_user_cache_key(user_id, cookie_hash)

            if user_cache_key in self._user_cache_registry:
                cached_content_name = self._user_cache_registry[user_cache_key]

                # Delete from Google Gen AI
                self.client.caches.delete(name=cached_content_name)

                # Remove from registry
                del self._user_cache_registry[user_cache_key]

                logger.info(f"Invalidated cached content for user {user_id}")
                return True

            return False

        except Exception as e:
            logger.error(f"Failed to invalidate cache for user {user_id}: {e}")
            return False

    def list_cached_content(self) -> List[Dict[str, Any]]:
        """
        List all cached content managed by this service.

        Returns:
            List of cached content information
        """
        try:
            cached_contents = []
            # List all cached content for this project
            for cache in self.client.caches.list():
                if cache.display_name and cache.display_name.startswith("karmayogi_user_"):
                    cached_contents.append({
                        "name": cache.name,
                        "display_name": cache.display_name,
                        "model": cache.model,
                        "expire_time": cache.expire_time,
                        "create_time": cache.create_time,
                        "usage_metadata": cache.usage_metadata
                    })
            return cached_contents
        except Exception as e:
            logger.error(f"Failed to list cached content: {e}")
            return []

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get statistics about the cache"""
        return {
            "active_user_caches": len(self._user_cache_registry),
            "user_cache_registry": dict(self._user_cache_registry),
            "model_name": self.model_name,
            "project_id": self.project_id,
            "location": self.location
        }


# Global instance
vertex_cache: Optional[VertexContentCache] = None


def initialize_vertex_cache(project_id: str, location: str = "us-central1",
                            credentials_path: Optional[str] = None) -> VertexContentCache:
    """
    Initialize the global Vertex AI content cache

    Args:
        project_id: Google Cloud project ID
        location: Vertex AI location (default: us-central1)
        credentials_path: Optional path to service account JSON file
    """
    global vertex_cache
    vertex_cache = VertexContentCache(project_id, location, credentials_path)
    return vertex_cache


async def get_cached_user_model(user_id: str, cookie: str, force_refresh: bool = False) -> Optional[str]:
    """
    Convenience function to get cached content name for user context.

    Args:
        user_id: User identifier
        cookie: Authentication cookie
        force_refresh: Force refresh of cached content

    Returns:
        Cached content name to use with generate_content, or None if failed
    """
    if not vertex_cache:
        logger.error("Vertex cache not initialized. Call initialize_vertex_cache() first.")
        return None

    cached_content_name = await vertex_cache.get_or_create_cached_content(
        user_id, cookie, force_refresh
    )

    if cached_content_name:
        return vertex_cache.get_model_with_cached_content(cached_content_name)

    return None


async def generate_with_user_context(user_id: str, cookie: str, prompt: str, force_refresh: bool = False) -> Optional[
    str]:
    """
    Generate content using Gemini with cached user context.

    Args:
        user_id: User identifier
        cookie: Authentication cookie
        prompt: User's message/prompt
        force_refresh: Force refresh of cached content

    Returns:
        Generated response or None if failed
    """
    if not vertex_cache:
        logger.error("Vertex cache not initialized. Call initialize_vertex_cache() first.")
        return None

    cached_content_name = await get_cached_user_model(user_id, cookie, force_refresh)

    if cached_content_name:
        try:
            # Use the Google Gen AI SDK with cached content
            from google.genai.types import GenerateContentConfig

            response = vertex_cache.client.models.generate_content(
                model=vertex_cache.model_name,
                contents=[Content(parts=[Part(text=prompt)], role="user")],
                config=GenerateContentConfig(
                    cached_content=cached_content_name
                )
            )
            return response.text
        except Exception as e:
            logger.error(f"Failed to generate content with cached context: {e}")
            return None

    return None