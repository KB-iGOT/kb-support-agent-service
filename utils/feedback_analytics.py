# utils/feedback_analytics.py
import logging

from utils.feedback_service import feedback_service

logger = logging.getLogger(__name__)

async def daily_feedback_aggregation():
    """Daily job to aggregate feedback data"""
    try:
        async with feedback_service.get_connection() as conn:
            await conn.execute("""
                INSERT INTO feedback_analytics (
                    date, agent_type, total_responses, total_feedback, 
                    upvotes, downvotes, feedback_rate, satisfaction_rate,
                    avg_response_time_ms
                )
                SELECT 
                    DATE(created_at) as date,
                    agent_type,
                    COUNT(*) as total_responses,
                    COUNT(CASE WHEN feedback_type IS NOT NULL THEN 1 END) as total_feedback,
                    COUNT(CASE WHEN feedback_type = 'upvote' THEN 1 END) as upvotes,
                    COUNT(CASE WHEN feedback_type = 'downvote' THEN 1 END) as downvotes,
                    ROUND(
                        COUNT(CASE WHEN feedback_type IS NOT NULL THEN 1 END) * 100.0 / COUNT(*), 2
                    ) as feedback_rate,
                    ROUND(
                        COUNT(CASE WHEN feedback_type = 'upvote' THEN 1 END) * 100.0 / 
                        NULLIF(COUNT(CASE WHEN feedback_type IS NOT NULL THEN 1 END), 0), 2
                    ) as satisfaction_rate,
                    AVG(response_time_ms) as avg_response_time_ms
                FROM llm_response_feedback
                WHERE DATE(created_at) = CURRENT_DATE - INTERVAL '1 day'
                GROUP BY DATE(created_at), agent_type
                ON CONFLICT (date, agent_type) DO UPDATE SET
                    total_responses = EXCLUDED.total_responses,
                    total_feedback = EXCLUDED.total_feedback,
                    upvotes = EXCLUDED.upvotes,
                    downvotes = EXCLUDED.downvotes,
                    feedback_rate = EXCLUDED.feedback_rate,
                    satisfaction_rate = EXCLUDED.satisfaction_rate,
                    avg_response_time_ms = EXCLUDED.avg_response_time_ms
            """)

        logger.info("Daily feedback aggregation completed")

    except Exception as e:
        logger.error(f"Error in daily aggregation: {e}")