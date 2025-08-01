import json
import logging
from typing import List
from google.adk.agents import Agent
from opik import track
from utils.request_context import RequestContext

logger = logging.getLogger(__name__)


@track(name="postgresql_enrollment_search_tool")
async def postgresql_enrollment_search_tool(user_message: str, request_context: RequestContext = None) -> dict:
    """
    PostgreSQL-based enrollment query tool wrapper (THREAD-SAFE)
    """
    logger.info(f"PostgreSQL enrollment search for: {user_message}")

    # Pass context to the tool instead of using globals
    return await postgresql_enrollment_query_tool_with_context(user_message, request_context)


@track(name="get_user_enrollments_tool")
async def get_user_enrollments_tool(user_message: str, request_context: RequestContext = None) -> dict:
    """Tool for retrieving user's course and event enrollments (THREAD-SAFE)"""
    try:
        logger.info("Getting user enrollments with request context")

        if not request_context or not request_context.user_context:
            return {"success": False, "error": "User context not available"}

        # Extract data from context (not globals)
        user_context = request_context.user_context
        chat_history = request_context.chat_history or []

        enrollment_summary = user_context.get('enrollment_summary', {})
        course_enrollments = user_context.get('course_enrollments', [])
        event_enrollments = user_context.get('event_enrollments', [])

        logger.info(f"get_user_enrollments_tool:: Enrollment Summary: {enrollment_summary}")

        # Process queries with context
        user_message_lower = user_message.lower()
        logger.info(f"Original User message for get_user_enrollments_tool: {user_message_lower}")

        # Rephrase if needed (using context, not globals)
        if len(user_message_lower.split()) < 4:
            rephrased_query = await _rephrase_query_with_context(user_message, chat_history)
        else:
            rephrased_query = user_message_lower

        logger.info(f"Rephrased User message for get_user_enrollments_tool: {rephrased_query}")

        system_message = f"""

## Role and Context
You are a helpful support agent for Karmayogi Bharat, a learning platform. Your primary task is to help users understand their course and event enrollments by analyzing their enrollment data and providing clear, conversational responses.

## Data Structure Understanding
The user's enrollment data contains:
- **course_enrollments**: Array of course objects with details like title, status, progress ('course_completion_percentage'), issued certificate id, certificate issued time, etc.
- **event_enrollments**: Array of event objects with similar structure
- **enrollment_summary**: Object containing aggregated statistics
- 'event_issued_certificate_id' and 'course_issued_certificate_id' contain the certificate IDs for events and courses respectively
- 'event_certificate_issued_on' and 'course_certificate_issued_on' contain the date when the certificate was issued for events and courses respectively

## Your Tasks
1. **Analyze the provided data** to understand the user's learning journey
2. **Answer specific questions** about courses, events, progress, or karma points
3. **Provide helpful insights** about their learning progress

## Special Instructions for Course Queries
1. **Always search for partial matches** in course names
2. **Look for key identifying words** rather than exact titles
3. **If you find a close match, assume that's what the user meant**
4. **Mention the full course title** in your response so the user knows which course you found

## Data Provided

@@ -99,84 +73,50 @@ async def get_user_enrollments_tool(user_message: str) -> dict:
```

### Summary Statistics:
- **Courses**: {len(course_enrollments)} total | {enrollment_summary.get('total_courses_completed', 0)} completed | {enrollment_summary.get('total_courses_in_progress', 0)} in progress | {enrollment_summary.get('total_courses_not_started', 0)} not started | {enrollment_summary.get('certified_courses_count', 0)} certified
- **Events**: {len(event_enrollments)} total | {enrollment_summary.get('total_events_completed', 0)} completed | {enrollment_summary.get('total_events_in_progress', 0)} in progress | {enrollment_summary.get('total_events_not_started', 0)} not started | {enrollment_summary.get('certified_events_count', 0)} certified
- **Karma Points**: {enrollment_summary.get('karma_points', 0)}

## Response Guidelines
- **Be conversational and friendly** - use natural language, not robotic responses
- **Focus on what the user asked** - if they have a specific question, answer it directly
- **Provide relevant details** - mention specific course/event names, progress percentages, deadlines
- **Use the actual data** - reference specific courses/events by name, not generic placeholders
- **Handle edge cases** - if data is missing or unclear, acknowledge it naturally
- **Don't expose internal field locations** - Never mention database field names or internal data structure locations to users
- **Focus on the answer** - Provide the requested information without technical implementation details
- **Keep responses user-friendly** - Avoid mentioning backend field names like "pinCode", "employmentDetails", etc.

## Example Response Patterns
- "I can see you're enrolled in [specific course name] and have completed [X]% of it..."
- "You've earned [X] karma points so far"
- "You have [X] courses in progress"
- "You have certificate '[certificate_id]' for the course '[course_name]'"

## Important Notes
- The user HAS enrolled in courses and events (the data confirms this)
- Always reference actual course/event names and details from the provided data
- If asked about specific courses/events, search through the arrays to find exact matches
- Calculate progress and statistics from the raw data when needed

Now, please analyze the user's enrollment data and provide a helpful response based on their query and learning progress.
"""

        try:
            # Call LLM with context (not globals)
            response = await _call_local_llm_with_context(system_message, rephrased_query, request_context)
            logger.info(f"get_user_enrollments_tool:: LLM response received")

            # Fallback response if LLM fails
            if not response or "don't have" in response.lower():
                response = f"""Based on your enrollment data:

📚 **Course Overview:**
- Total Enrolled Courses: {len(course_enrollments)} courses
- Completed: {enrollment_summary.get('total_courses_completed', 0)} courses
- In Progress: {enrollment_summary.get('total_courses_in_progress', 0)} courses  
- Certificates Earned: {enrollment_summary.get('certified_courses_count', 0)}

🎯 **Event Overview:**
- Total Enrolled Events: {len(event_enrollments)} events
- Completed Events: {enrollment_summary.get('total_events_completed', 0)} events

🏆 **Your Progress:**
- Karma Points: {enrollment_summary.get('karma_points', 0)}

For more specific information, please let me know what you'd like to know!"""

        except Exception as llm_error:
            logger.error(f"LLM call failed: {llm_error}")
            response = f"""Here's your enrollment summary:

📚 **Your Courses:** {len(course_enrollments)} courses
🎯 **Your Events:** {len(event_enrollments)} events  
🏆 **Karma Points:** {enrollment_summary.get('karma_points', 0)}

What specific information would you like about your courses?"""

        return {
            "success": True,
            "response": response,
            "data_type": "enrollments",
            "search_type": "general"
        }

    except Exception as e:
        logger.error(f"Error in get_user_enrollments_tool: {e}")
        return {"success": False, "error": str(e)}


@track(name="get_user_profile_tool")
async def get_user_profile_tool(user_message: str, request_context: RequestContext = None) -> dict:
    """Tool for retrieving user's profile information (THREAD-SAFE)"""
    try:
        logger.info("Getting user profile with request context")

        if not request_context or not request_context.user_context:
            return {"success": False, "error": "User context not available"}

        user_context = request_context.user_context
        chat_history = request_context.chat_history or []

        enrollment_summary = user_context.get('enrollment_summary', {})
        # Build history context
        history_context = ""
        if chat_history:
            history_context = "\n\nRECENT CONVERSATION HISTORY:\n"
            for msg in chat_history[-6:]:
                role = "User" if msg.role == "user" else "Assistant"
                content = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
                history_context += f"{role}: {content}\n"

        logger.info(f"Original User message for get_user_profile_tool: {user_message}")

        # Rephrase if needed
        if len(user_message.split()) < 4:
            rephrased_query = await _rephrase_query_with_context(user_message, chat_history)
        else:
            rephrased_query = user_message

        logger.info(f"Rephrased User message for get_user_profile_tool: {rephrased_query}")

        profile_data = user_context.get('profile', {})

        system_message = f"""
## Role and Context
You are a helpful support agent for Karmayogi Bharat, a learning platform. Your primary task is to help users understand and manage their profile information by analyzing their profile data and providing clear, conversational responses about their account details

## Your Tasks
1. **Analyze the provided data** to understand the user's profile information
2. **Answer specific questions** about user's profile
3. **Provide helpful insights** about their profile information

## Data Provided
### Profile Data:
{profile_data}

### Enrollment Summary:
```json
{json.dumps(enrollment_summary, indent=2)}
```

### Chat History Context:
{history_context}


## Response Guidelines
- **Be conversational and helpful** - use natural, friendly language
- **Focus on the user's specific question** - answer directly what they asked
- **Provide relevant details** - mention specific profile fields, settings, or achievements
- **Use actual data** - reference specific information from their profile, not generic examples
- **Respect privacy** - be mindful when discussing sensitive information
- **Don't expose internal field locations** - Never mention database field names or internal data structure locations to users
- **Focus on the answer** - Provide the requested information without technical implementation details
- **Keep responses user-friendly** - Avoid mentioning backend field names like "pinCode", "employmentDetails", etc.

## Important Notes
- Always use the actual profile data provided - don't make assumptions
- If information is missing or unclear, acknowledge it naturally
- Be sensitive when discussing personal information
- Encourage profile completion by highlighting benefits
- Explain privacy implications when discussing settings
- Reference specific achievement names, dates, and details
- If asked about updating information, provide clear guidance

## Privacy and Security Considerations
- Never suggest sharing sensitive information inappropriately
- Explain privacy settings clearly when asked
- Be mindful of organizational hierarchy when discussing reporting structure
- Respect user preferences for communication and notifications

Now, please analyze the user's profile data and provide a helpful response based on their query and current profile status.
"""

        logger.info(f"get_user_profile_tool:: Processing query with LLM")
        response = await _call_local_llm_with_context(system_message, rephrased_query, request_context)
        logger.info(f"get_user_profile_tool:: LLM response received")

        return {
            "success": True,
            "response": response,
            "data_type": "profile"
        }

    except Exception as e:
        logger.error(f"Error in get_user_profile_tool: {e}")
        return {"success": False, "error": str(e)}


# Helper functions that use context instead of globals
async def _rephrase_query_with_context(user_message: str, chat_history: List) -> str:
    """Rephrase query using context instead of globals"""
    try:
        # Import here to avoid circular imports
        from utils.common_utils import rephrase_query_with_history
        return await rephrase_query_with_history(user_message, chat_history)
    except Exception as e:
        logger.error(f"Error rephrasing query: {e}")
        return user_message


async def _call_local_llm_with_context(system_message: str, user_message: str, request_context: RequestContext) -> str:
    """Call local LLM with context instead of globals"""
    try:
        from utils.common_utils import call_local_llm
        return await call_local_llm(system_message, user_message)
    except Exception as e:
        logger.error(f"Error calling local LLM: {e}")
        return ""


# Updated PostgreSQL enrollment query tool
async def postgresql_enrollment_query_tool_with_context(user_message: str, request_context: RequestContext) -> dict:
    """
    PostgreSQL-based enrollment query tool with context (THREAD-SAFE)
    """
    try:
        if not request_context or not request_context.user_context:
            return {"success": False, "error": "User context not available"}

        user_context = request_context.user_context
        enrollment_summary = user_context.get('enrollment_summary', {})

        logger.info(f"postgresql_enrollment_query_tool_with_context:: Enrollment Summary: {enrollment_summary}")

        user_id = request_context.user_id
        if not user_id:
            return {"success": False, "error": "User ID not available"}

        logger.info(f"PostgreSQL enrollment query for user {user_id}: {user_message}")

        # Execute PostgreSQL query
        from utils.postgresql_enrollment_service import postgresql_service
        query_result = await postgresql_service.query_enrollments(user_id, user_message)

        if not query_result.get("success"):
            return {
                "success": False,
                "error": query_result.get("error", "Query execution failed"),
                "fallback_message": "I'll help you with a general search instead."
            }

        results = query_result.get("results", [])
        sql_query = query_result.get("sql_query", "")
        generation_method = query_result.get("generation_method", "unknown")

        logger.info(f"PostgreSQL query returned {len(results)} results using {generation_method}")

        if not results:
            return {
                "success": True,
                "response": "No enrollments found matching your criteria.",
                "sql_query": sql_query,
                "result_count": 0,
                "generation_method": generation_method
            }

        # Process results with LLM
        system_message = f"""
You are analyzing enrollment query results from PostgreSQL.

## User Query: {user_message}
## SQL Query Executed: {sql_query}
## Results Found: {len(results)}

### Enrollment Summary:
```json
{json.dumps(enrollment_summary, indent=2)}
```

## Query Results:
```json
{json.dumps(results, indent=2, default=str)}
```

Provide a clear, conversational response based on the data.
"""

        try:
            response = await _call_local_llm_with_context(system_message, user_message, request_context)

            return {
                "success": True,
                "response": response,
                "sql_query": sql_query,
                "result_count": len(results),
                "query_type": "postgresql",
                "generation_method": generation_method
            }

        except Exception as llm_error:
            logger.error(f"LLM processing failed: {llm_error}")
            return {
                "success": True,
                "response": f"Found {len(results)} enrollments matching your query.",
                "sql_query": sql_query,
                "result_count": len(results),
                "query_type": "postgresql",
                "generation_method": generation_method
            }

    except Exception as e:
        logger.error(f"Error in PostgreSQL enrollment query tool: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def create_user_profile_info_sub_agent(opik_tracer, request_context: RequestContext) -> Agent:
    """Create the user profile info sub-agent with request context (THREAD-SAFE)"""

    # Create tools that will receive context as parameter
    def make_tool_with_context(tool_func):
        """Wrapper to inject request context into tools"""

        async def wrapped_tool(user_message: str) -> dict:
            return await tool_func(user_message, request_context)

        wrapped_tool.__name__ = tool_func.__name__
        return wrapped_tool

    tools = [
        make_tool_with_context(get_user_enrollments_tool),
        make_tool_with_context(get_user_profile_tool),
        make_tool_with_context(postgresql_enrollment_search_tool),
    ]

    # Build chat history context for LLM
    history_context = ""
    chat_history = request_context.chat_history or []
    if chat_history:
        history_context = "\n\nRECENT CONVERSATION HISTORY:\n"
        for msg in chat_history[-6:]:
            role = "User" if msg.role == "user" else "Assistant"
            content = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
            history_context += f"{role}: {content}\n"

    agent = Agent(
        name="user_profile_info_sub_agent",
        model="gemini-2.0-flash-001",
        description="Specialized sub-agent that handles user profile and enrolments specific queries",
        instruction=f"""
You are a specialized sub-agent that handles user-specific queries about:
    - User's Course and event enrollments
    - User's Learning progress and achievements  
    - User profile information
    - Karma points and certificates

    ## Tool Selection Strategy:
    
    - **postgresql_enrollment_search_tool** - PRIMARY TOOL for listing and complex filtering queries:
        - "List all my completed courses that don't have certificates"
        - "Show me courses I completed but no certificate"
        - "Which events have I completed with certificates?"
        - "Find all courses with less than 50% progress"
        - "Show me recent course enrollments"
        - "Count my certified courses"
        - "How much have I completed in course [name]"
        - "Do I have certificate for [specific course]"
        - "What's my progress in [event name]"
        - "Status of [course/event name]"

    - **get_user_enrollments_tool**: Use for general statistics and broad queries:
        - "How many courses do I have"
        - "How many courses are incomplete?"
        - "Total karma points"

    - **get_user_profile_tool**: Use for profile information queries

    Always provide helpful, accurate responses based on the user's actual data.

    {history_context}
""",
        tools=tools,
        before_agent_callback=opik_tracer.before_agent_callback,
        after_agent_callback=opik_tracer.after_agent_callback,
        before_model_callback=opik_tracer.before_model_callback,
        after_model_callback=opik_tracer.after_model_callback,
        before_tool_callback=opik_tracer.before_tool_callback,
        after_tool_callback=opik_tracer.after_tool_callback,
    )

    return agent