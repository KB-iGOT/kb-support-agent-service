# utils/feedback_service.py
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

from utils.postgresql_enrollment_service import postgresql_service

logger = logging.getLogger(__name__)


class FeedbackService:
    """Service for handling LLM response feedback"""

    def __init__(self):
        self.pool = postgresql_service.pool

    @asynccontextmanager
    async def get_connection(self):
        """Get database connection from shared pool"""
        async with self.pool.acquire() as connection:
            yield connection

    async def submit_feedback(
            self,
            user_id: str,
            session_id: str,
            message_id: str,
            user_query: str,
            llm_response: str,
            feedback_type: str,  # 'upvote' or 'downvote'
            feedback_reason: Optional[str] = None,
            feedback_comment: Optional[str] = None,
            context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Submit user feedback for an LLM response"""

        try:
            async with self.get_connection() as conn:
                # Check if feedback already exists
                existing = await conn.fetchrow("""
                    SELECT feedback_id, feedback_type 
                    FROM llm_response_feedback 
                    WHERE user_id = $1 AND session_id = $2 AND message_id = $3
                """, user_id, session_id, message_id)

                if existing:
                    # Update existing feedback
                    await conn.execute("""
                        UPDATE llm_response_feedback 
                        SET feedback_type = $1, feedback_reason = $2, 
                            feedback_comment = $3, updated_at = CURRENT_TIMESTAMP
                        WHERE user_id = $4 AND session_id = $5 AND message_id = $6
                    """, feedback_type, feedback_reason, feedback_comment,
                                       user_id, session_id, message_id)

                    logger.info(f"Updated feedback for message {message_id}: {feedback_type}")
                    return {
                        "success": True,
                        "action": "updated",
                        "feedback_id": str(existing['feedback_id'])
                    }
                else:
                    # Insert new feedback
                    result = await conn.fetchrow("""
                        INSERT INTO llm_response_feedback (
                            user_id, session_id, message_id, user_query, llm_response,
                            feedback_type, feedback_reason, feedback_comment,
                            agent_type, conversation_turn, response_time_ms,
                            user_language, is_anonymous
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                        RETURNING feedback_id
                    """,
                                                 user_id, session_id, message_id, user_query, llm_response,
                                                 feedback_type, feedback_reason, feedback_comment,
                                                 context.get('agent_type', 'unknown'),
                                                 context.get('conversation_turn', 1),
                                                 context.get('response_time_ms', 0),
                                                 context.get('user_language', 'en'),
                                                 context.get('is_anonymous', False)
                                                 )

                    logger.info(f"Created new feedback for message {message_id}: {feedback_type}")
                    return {
                        "success": True,
                        "action": "created",
                        "feedback_id": str(result['feedback_id'])
                    }

        except Exception as e:
            logger.error(f"Error submitting feedback: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def get_feedback_reasons(self) -> List[Dict[str, Any]]:
        """Get available feedback reasons for downvotes"""
        try:
            async with self.get_connection() as conn:
                rows = await conn.fetch("""
                    SELECT reason_code, reason_display, reason_description
                    FROM feedback_reasons 
                    WHERE is_active = true 
                    ORDER BY sort_order
                """)

                return [dict(row) for row in rows]

        except Exception as e:
            logger.error(f"Error fetching feedback reasons: {e}")
            return []

    async def get_feedback_analytics(
            self,
            start_date: Optional[datetime] = None,
            end_date: Optional[datetime] = None,
            agent_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get feedback analytics for the specified period"""

        if not start_date:
            start_date = datetime.now() - timedelta(days=30)
        if not end_date:
            end_date = datetime.now()

        try:
            async with self.get_connection() as conn:
                # Build query conditions
                conditions = ["created_at >= $1", "created_at <= $2"]
                params = [start_date, end_date]

                if agent_type:
                    conditions.append(f"agent_type = ${len(params) + 1}")
                    params.append(agent_type)

                where_clause = " AND ".join(conditions)

                # Get aggregated feedback data
                query = f"""
                    SELECT 
                        agent_type,
                        COUNT(*) as total_feedback,
                        COUNT(CASE WHEN feedback_type = 'upvote' THEN 1 END) as upvotes,
                        COUNT(CASE WHEN feedback_type = 'downvote' THEN 1 END) as downvotes,
                        AVG(response_time_ms) as avg_response_time,
                        ROUND(
                            COUNT(CASE WHEN feedback_type = 'upvote' THEN 1 END) * 100.0 / 
                            COUNT(*), 2
                        ) as satisfaction_rate
                    FROM llm_response_feedback 
                    WHERE {where_clause}
                    GROUP BY agent_type
                    ORDER BY agent_type
                """

                rows = await conn.fetch(query, *params)

                return {
                    "success": True,
                    "period": {
                        "start_date": start_date.isoformat(),
                        "end_date": end_date.isoformat()
                    },
                    "analytics": [dict(row) for row in rows]
                }

        except Exception as e:
            logger.error(f"Error fetching analytics: {e}")
            return {
                "success": False,
                "error": str(e)
            }


# Global feedback service instance
feedback_service = FeedbackService()