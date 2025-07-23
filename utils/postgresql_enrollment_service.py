# utils/postgresql_enrollment_service.py - Enhanced with Gemini SQL Generation
import logging
import os
import re
import json
from typing import Dict, List, Any, Optional, Tuple
import asyncpg
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


class PostgreSQLEnrollmentService:
    """
    Service for handling PostgreSQL queries on user enrollments
    Uses Gemini API to convert natural language queries to SQL
    """

    def __init__(self):
        self.db_url = os.getenv("POSTGRESQL_URL", "postgresql://username:password@localhost:5432/karmayogi_db")
        self.pool = None

    async def initialize_pool(self):
        """Initialize connection pool"""
        if not self.pool:
            try:
                self.pool = await asyncpg.create_pool(
                    self.db_url,
                    min_size=1,
                    max_size=10,
                    command_timeout=30
                )
                logger.info("PostgreSQL connection pool initialized")
            except Exception as e:
                logger.error(f"Failed to initialize PostgreSQL pool: {e}")
                raise

    @asynccontextmanager
    async def get_connection(self):
        """Get database connection from pool"""
        if not self.pool:
            await self.initialize_pool()

        async with self.pool.acquire() as connection:
            yield connection

    async def store_enrollments(self, user_id: str, session_id: str,
                                course_enrollments: List[Dict],
                                event_enrollments: List[Dict]) -> bool:
        """Store user enrollments in PostgreSQL"""
        try:
            async with self.get_connection() as conn:
                # Delete existing enrollments for this user to avoid duplicates
                await conn.execute(
                    "DELETE FROM user_enrollments WHERE user_id = $1",
                    user_id
                )

                # Insert course enrollments
                for course in course_enrollments:
                    await conn.execute("""
                        INSERT INTO user_enrollments (
                            session_id, user_id, type, enrollment_date, completion_percentage,
                            issued_certificate_id, certificate_issued_on, name, identifier, batch_id, 
                            total_content_count, completed_on, completion_status
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                        ON CONFLICT (user_id, identifier) DO UPDATE SET
                            completion_percentage = EXCLUDED.completion_percentage,
                            issued_certificate_id = EXCLUDED.issued_certificate_id,
                            certificate_issued_on = EXCLUDED.certificate_issued_on,
                            completed_on = EXCLUDED.completed_on,
                            completion_status = EXCLUDED.completion_status
                    """,
                                       session_id, user_id, 'course',
                                       self._parse_date(course.get('course_enrolment_date')),
                                       float(course.get('course_completion_percentage', 0)),
                                       course.get('course_issued_certificate_id'),
                                       self._parse_date(course.get('course_certificate_issued_on')),
                                       course.get('course_name', ''),
                                       course.get('course_identifier', ''),
                                       course.get('course_batch_id', ''),
                                       int(course.get('course_total_content_count', 0)),
                                       self._parse_date(course.get('course_last_accessed_on')),
                                       course.get('course_completion_status', 'not started')
                                       )

                # Insert event enrollments
                for event in event_enrollments:
                    await conn.execute("""
                        INSERT INTO user_enrollments (
                            session_id, user_id, type, enrollment_date, completion_percentage,
                            issued_certificate_id, certificate_issued_on, name, identifier, batch_id, 
                            completed_on, completion_status
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                        ON CONFLICT (user_id, identifier) DO UPDATE SET
                            completion_percentage = EXCLUDED.completion_percentage,
                            issued_certificate_id = EXCLUDED.issued_certificate_id,
                            certificate_issued_on = EXCLUDED.certificate_issued_on,
                            completed_on = EXCLUDED.completed_on,
                            completion_status = EXCLUDED.completion_status
                    """,
                                       session_id, user_id, 'event',
                                       self._parse_date(event.get('event_enrolment_date')),
                                       float(event.get('event_completion_percentage', 0)),
                                       event.get('event_issued_certificate_id'),
                                       self._parse_date(event.get('event_certificate_issued_on')),
                                       event.get('event_name', ''),
                                       event.get('event_identifier', ''),
                                       event.get('event_batch_id', ''),
                                       self._parse_date(event.get('event_last_accessed_on')),
                                       event.get('event_completion_status', 'not started')
                                       )

                logger.info(
                    f"Stored {len(course_enrollments)} courses and {len(event_enrollments)} events for user {user_id}")
                return True

        except Exception as e:
            logger.error(f"Error storing enrollments: {e}")
            return False

    def _parse_date(self, date_value) -> Optional[int]:
        """Parse date value to timestamp"""
        if date_value is None or date_value == '':
            return None
        try:
            if isinstance(date_value, str):
                # Try to parse as timestamp
                return int(date_value)
            elif isinstance(date_value, (int, float)):
                return int(date_value)
        except (ValueError, TypeError):
            pass
        return None

    async def query_enrollments(self, user_id: str, user_query: str) -> Dict[str, Any]:
        """
        Convert natural language query to SQL using Gemini API and execute
        """
        try:
            # Convert user query to SQL using Gemini
            sql_query, params = await self._convert_to_sql_with_gemini(user_id, user_query)

            if not sql_query:
                # Fallback to rule-based conversion
                logger.warning("Gemini SQL conversion failed, using fallback")
                sql_query, params = await self._convert_to_sql_fallback(user_id, user_query)

            if not sql_query:
                return {
                    "success": False,
                    "error": "Could not convert query to SQL",
                    "user_query": user_query
                }

            # Execute query
            async with self.get_connection() as conn:
                rows = await conn.fetch(sql_query, *params)

                # Convert rows to list of dictionaries
                results = [dict(row) for row in rows]

                logger.info(f"Query executed successfully, returned {len(results)} rows")

                return {
                    "success": True,
                    "results": results,
                    "sql_query": sql_query,
                    "user_query": user_query,
                    "count": len(results),
                    "generation_method": "gemini"
                }

        except Exception as e:
            logger.error(f"Error executing enrollment query: {e}")
            return {
                "success": False,
                "error": str(e),
                "user_query": user_query
            }

    async def list_enrollments(self, user_id: str) -> Dict[str, Any]:
        """List all enrollments for a user"""
        try:
            async with self.get_connection() as conn:
                query = """
                SELECT 
                    type, name, completion_percentage, completion_status,
                    issued_certificate_id, certificate_issued_on, enrollment_date,
                    completed_on, identifier, batch_id
                FROM user_enrollments 
                WHERE user_id = $1
                ORDER BY enrollment_date DESC
                LIMIT 1000
                """
                rows = await conn.fetch(query, user_id)
                results = [dict(row) for row in rows]

                return {
                    "success": True,
                    "results": results,
                    "count": len(results)
                }

        except Exception as e:
            logger.error(f"Error listing enrollments: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def _convert_to_sql_with_gemini(self, user_id: str, user_query: str) -> Tuple[str, List]:
        """
        Convert natural language query to PostgreSQL query using Gemini API
        """
        try:
            # Import the Gemini API function from main
            from main import _call_gemini_api

            # Create detailed prompt for SQL generation
            sql_generation_prompt = f"""
You are an expert PostgreSQL query generator for a learning management system. Convert the following natural language query into a valid PostgreSQL query.

## Database Schema:
```sql
CREATE TABLE user_enrollments (
    id BIGSERIAL PRIMARY KEY,
    session_id VARCHAR(255) NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    type VARCHAR(10) NOT NULL CHECK (type IN ('course', 'event')),
    enrollment_date BIGINT,
    completion_percentage NUMERIC(5,2) DEFAULT 0.00,
    issued_certificate_id VARCHAR(255),
    certificate_issued_on BIGINT,
    name TEXT NOT NULL,
    identifier VARCHAR(255) NOT NULL,
    batch_id VARCHAR(255),
    total_content_count INTEGER DEFAULT 0,
    completed_on BIGINT,
    completion_status VARCHAR(20) DEFAULT 'not started' CHECK (completion_status IN ('not started', 'in progress', 'completed')),
    inserted_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Field Explanations:
- `type`: 'course' or 'event'
- `completion_status`: 'not started', 'in progress', 'completed'
- `completion_percentage`: 0.00 to 100.00
- `issued_certificate_id`: NULL if no certificate, string value if certificate exists
- `name`: Course/event name (searchable with ILIKE for partial matches)
- `enrollment_date`, `certificate_issued_on`, `completed_on`: BIGINT timestamps

## User Query: "{user_query}"
## User ID: {user_id}

## Instructions:
1. **ALWAYS include WHERE user_id = $1** as the first condition
2. **Use parameterized queries** with $1, $2, $3, etc. for user inputs
3. **Return ONLY the SQL query and parameters** in this exact JSON format:
   ```json
   {{
     "sql": "SELECT ... FROM user_enrollments WHERE user_id = $1 AND ...",
     "params": ["{user_id}", "param2", "param3"]
   }}
   ```
4. **Include these standard fields in SELECT**: type, name, completion_percentage, completion_status, issued_certificate_id, certificate_issued_on, enrollment_date, completed_on, identifier, batch_id
5. **For count queries**, use: SELECT type, completion_status, COUNT(*) as count FROM user_enrollments WHERE user_id = $1 ... GROUP BY type, completion_status
6. **For certificate queries**:
   - "without certificate" or "no certificate" → issued_certificate_id IS NULL
   - "with certificate" or "have certificate" → issued_certificate_id IS NOT NULL
7. **For status queries**:
   - "completed" → completion_status = 'completed'
   - "in progress" → completion_status = 'in progress'
   - "not started" → completion_status = 'not started'
8. **For name searches**, use: name ILIKE $2 with parameter '%search_term%'
9. **Always add LIMIT 100** for non-count queries to prevent huge results
10. **Use proper ORDER BY** for meaningful results (e.g., ORDER BY name, ORDER BY enrollment_date DESC)

## Example Conversions:
- "List completed courses without certificates" → 
  ```json
  {{
    "sql": "SELECT type, name, completion_percentage, completion_status, issued_certificate_id, certificate_issued_on, enrollment_date, completed_on, identifier, batch_id FROM user_enrollments WHERE user_id = $1 AND type = 'course' AND completion_status = 'completed' AND issued_certificate_id IS NULL ORDER BY name LIMIT 100",
    "params": ["{user_id}"]
  }}
  ```

- "How many courses do I have?" →
  ```json
  {{
    "sql": "SELECT type, completion_status, COUNT(*) as count FROM user_enrollments WHERE user_id = $1 AND type = 'course' GROUP BY type, completion_status ORDER BY type, completion_status",
    "params": ["{user_id}"]
  }}
  ```

- "Find courses named Python" →
  ```json
  {{
    "sql": "SELECT type, name, completion_percentage, completion_status, issued_certificate_id, certificate_issued_on, enrollment_date, completed_on, identifier, batch_id FROM user_enrollments WHERE user_id = $1 AND type = 'course' AND name ILIKE $2 ORDER BY name LIMIT 100",
    "params": ["{user_id}", "%Python%"]
  }}
  ```

Convert the user query above and return ONLY the JSON response with sql and params fields.
"""

            # Call Gemini API
            gemini_response = await _call_gemini_api(sql_generation_prompt)

            if not gemini_response:
                logger.warning("Gemini API returned empty response for SQL generation")
                return "", []

            # Parse JSON response
            try:
                # Clean up the response - remove any markdown formatting
                cleaned_response = gemini_response.strip()
                if cleaned_response.startswith("```json"):
                    cleaned_response = cleaned_response[7:]
                if cleaned_response.endswith("```"):
                    cleaned_response = cleaned_response[:-3]
                cleaned_response = cleaned_response.strip()

                # Parse JSON
                response_data = json.loads(cleaned_response)

                sql_query = response_data.get("sql", "")
                params = response_data.get("params", [])

                if not sql_query:
                    logger.warning("Gemini response missing SQL query")
                    return "", []

                # Validate the SQL query has user_id parameter
                if "user_id = $1" not in sql_query and "user_id=$1" not in sql_query:
                    logger.warning("Generated SQL missing user_id filter, adding it")
                    # Insert user_id filter if missing
                    if "WHERE" in sql_query.upper():
                        sql_query = sql_query.replace("WHERE", f"WHERE user_id = $1 AND", 1)
                        params.insert(0, user_id)
                    else:
                        # Add WHERE clause
                        from_index = sql_query.upper().find("FROM user_enrollments")
                        if from_index != -1:
                            insert_point = from_index + len("FROM user_enrollments")
                            sql_query = sql_query[:insert_point] + f" WHERE user_id = $1" + sql_query[insert_point:]
                            params.insert(0, user_id)

                logger.info(f"Gemini generated SQL: {sql_query}")
                logger.info(f"Gemini generated params: {params}")

                return sql_query, params

            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse Gemini JSON response: {e}")
                logger.error(f"Raw response: {gemini_response}")
                return "", []

        except Exception as e:
            logger.error(f"Error in Gemini SQL conversion: {e}")
            return "", []

    async def _convert_to_sql_fallback(self, user_id: str, user_query: str) -> Tuple[str, List]:
        """
        Fallback rule-based SQL conversion (original implementation)
        """
        query_lower = user_query.lower().strip()

        # Base query
        base_query = """
        SELECT 
            type,
            name,
            completion_percentage,
            completion_status,
            issued_certificate_id,
            certificate_issued_on,
            enrollment_date,
            completed_on,
            identifier,
            batch_id
        FROM user_enrollments 
        WHERE user_id = $1
        """

        params = [user_id]
        conditions = []
        order_by = ""

        # Parse common query patterns

        # Certificate-related queries
        if "certificate" in query_lower:
            if any(phrase in query_lower for phrase in
                   ["no certificate", "without certificate", "don't have certificate", "no cert"]):
                conditions.append("issued_certificate_id IS NULL")
            elif any(phrase in query_lower for phrase in ["have certificate", "with certificate", "certified"]):
                conditions.append("issued_certificate_id IS NOT NULL")

        # Completion status queries
        if "completed" in query_lower and "not completed" not in query_lower:
            conditions.append("completion_status = 'completed'")
        elif "not completed" in query_lower or "incomplete" in query_lower:
            conditions.append("completion_status != 'completed'")
        elif "in progress" in query_lower:
            conditions.append("completion_status = 'in progress'")
        elif "not started" in query_lower:
            conditions.append("completion_status = 'not started'")

        # Type filters
        if "course" in query_lower and "event" not in query_lower:
            conditions.append("type = 'course'")
        elif "event" in query_lower and "course" not in query_lower:
            conditions.append("type = 'event'")

        # Progress percentage queries
        if "100%" in query_lower or "fully completed" in query_lower:
            conditions.append("completion_percentage = 100")
        elif "50%" in query_lower:
            conditions.append("completion_percentage >= 50")
        elif "less than" in query_lower and "%" in query_lower:
            # Extract percentage
            percentage_match = re.search(r'less than (\d+)%', query_lower)
            if percentage_match:
                percentage = int(percentage_match.group(1))
                conditions.append(f"completion_percentage < ${len(params) + 1}")
                params.append(percentage)
        elif "more than" in query_lower and "%" in query_lower:
            percentage_match = re.search(r'more than (\d+)%', query_lower)
            if percentage_match:
                percentage = int(percentage_match.group(1))
                conditions.append(f"completion_percentage > ${len(params) + 1}")
                params.append(percentage)

        # Name-based search
        if "named" in query_lower or "called" in query_lower:
            # Extract course/event name
            name_patterns = [
                r'named "([^"]+)"',
                r"named '([^']+)'",
                r'called "([^"]+)"',
                r"called '([^']+)'",
                r'named ([A-Za-z0-9\s]+)',
                r'called ([A-Za-z0-9\s]+)'
            ]

            for pattern in name_patterns:
                match = re.search(pattern, query_lower)
                if match:
                    name = match.group(1).strip()
                    conditions.append(f"name ILIKE ${len(params) + 1}")
                    params.append(f"%{name}%")
                    break

        # Recent queries
        if "recent" in query_lower or "latest" in query_lower:
            order_by = "ORDER BY enrollment_date DESC"
        elif "oldest" in query_lower:
            order_by = "ORDER BY enrollment_date ASC"

        # Count queries
        if any(phrase in query_lower for phrase in ["how many", "count", "total number"]):
            base_query = """
            SELECT 
                type,
                completion_status,
                COUNT(*) as count
            FROM user_enrollments 
            WHERE user_id = $1
            """
            if conditions:
                base_query += " AND " + " AND ".join(conditions)
            base_query += " GROUP BY type, completion_status ORDER BY type, completion_status"
        else:
            # Regular query
            if conditions:
                base_query += " AND " + " AND ".join(conditions)
            if order_by:
                base_query += " " + order_by
            # Limit results to prevent huge responses
            base_query += " LIMIT 100"

        return base_query, params

    async def get_enrollment_summary(self, user_id: str) -> Dict[str, Any]:
        """Get summary statistics for user enrollments"""
        try:
            async with self.get_connection() as conn:
                summary_query = """
                SELECT 
                    type,
                    completion_status,
                    COUNT(*) as count,
                    AVG(completion_percentage) as avg_progress,
                    COUNT(CASE WHEN issued_certificate_id IS NOT NULL THEN 1 END) as certified_count
                FROM user_enrollments 
                WHERE user_id = $1
                GROUP BY type, completion_status
                ORDER BY type, completion_status
                """

                rows = await conn.fetch(summary_query, user_id)
                results = [dict(row) for row in rows]

                return {
                    "success": True,
                    "summary": results
                }

        except Exception as e:
            logger.error(f"Error getting enrollment summary: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def health_check(self) -> Dict[str, Any]:
        """Check PostgreSQL connection health"""
        try:
            async with self.get_connection() as conn:
                result = await conn.fetchval("SELECT 1")
                return {
                    "status": "healthy",
                    "database": "connected",
                    "test_query": "passed"
                }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)
            }

    async def close(self):
        """Close connection pool"""
        if self.pool:
            await self.pool.close()
            logger.info("PostgreSQL connection pool closed")


# Global service instance
postgresql_service = PostgreSQLEnrollmentService()


# Tool function for the agent
async def postgresql_enrollment_query_tool(user_message: str) -> dict:
    """
    PostgreSQL-based enrollment query tool with Gemini SQL generation
    Converts natural language to SQL using Gemini API and executes against enrollment database
    """
    try:
        from main import user_context, current_chat_history, _call_local_llm

        if not user_context:
            return {"success": False, "error": "User context not available"}

        user_id = user_context.get('user_id')
        if not user_id:
            return {"success": False, "error": "User ID not available"}

        logger.info(f"PostgreSQL enrollment query for user {user_id}: {user_message}")

        # Execute PostgreSQL query (now with Gemini)
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

        # Process results with LLM for natural language response
        system_message = f"""
You are a helpful assistant analyzing enrollment query results from a PostgreSQL database.

## User Query: {user_message}
## SQL Query Executed: {sql_query}
## SQL Generation Method: {generation_method}
## Results Found: {len(results)}

## Query Results:
```json
{json.dumps(results, indent=2, default=str)}
```

## Your Task:
Analyze the SQL query results and provide a clear, conversational response that:
1. **Directly answers the user's question** based on the data
2. **Uses natural language** - avoid technical jargon
3. **Mentions specific details** from the results (course/event names, counts, percentages)
4. **Organizes information clearly** - use bullet points or numbered lists when helpful
5. **Provides context** - explain what the numbers mean in practical terms

## Response Guidelines:
- Start with a direct answer to their question
- Include relevant counts and statistics
- Mention specific course/event names when relevant
- If showing a list, limit to most relevant items (max 10)
- End with an offer to help with more specific queries if needed

## Data Field Meanings:
- completion_percentage: 0-100 (how much they've completed)
- completion_status: 'not started', 'in progress', 'completed'
- issued_certificate_id: present if they have a certificate
- type: 'course' or 'event'

Provide a helpful, conversational response based on the query results.
"""

        try:
            response = await _call_local_llm(system_message,
                                             f"Analyze these enrollment query results for: {user_message}")

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
            # Fallback response
            return {
                "success": True,
                "response": f"Found {len(results)} enrollments matching your query. The results include courses and events with their completion status and certificate information.",
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


# Initialize enrollments in PostgreSQL
async def initialize_user_enrollments_in_postgresql(user_id: str, session_id: str,
                                                    course_enrollments: List[Dict],
                                                    event_enrollments: List[Dict]) -> bool:
    """
    Initialize user enrollments in PostgreSQL database
    Call this when user details are fetched/cached
    """
    try:
        success = await postgresql_service.store_enrollments(
            user_id, session_id, course_enrollments, event_enrollments
        )

        if success:
            logger.info(f"Successfully initialized PostgreSQL enrollments for user {user_id}")
        else:
            logger.error(f"Failed to initialize PostgreSQL enrollments for user {user_id}")

        return success

    except Exception as e:
        logger.error(f"Error initializing PostgreSQL enrollments: {e}")
        return False