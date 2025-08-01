# agents/generic_sub_agent.py - THREAD SAFE VERSION
import logging
from google.adk.agents import Agent
from opik import track
from utils.request_context import RequestContext

logger = logging.getLogger(__name__)


@track(name="general_platform_support_tool")
async def general_platform_support_tool_with_context(user_message: str, request_context: RequestContext) -> dict:
    """Thread-safe version of general platform support tool"""
    try:
        if not request_context:
            return {"success": False, "error": "Request context not available"}

        # Get context data from request_context instead of global imports
        current_chat_history = request_context.chat_history or []
        user_context = request_context.user_context or {}

        # Import functions locally to avoid global state issues
        from utils.common_utils import (rephrase_query_with_history, call_gemini_api, call_local_llm, EMBEDDING_MODEL_NAME)

        # Build chat history context
        history_context = ""
        if current_chat_history:
            history_context = "\n\nRECENT CONVERSATION HISTORY:\n"
            for msg in current_chat_history[-6:]:
                role = "User" if msg.role == "user" else "Assistant"
                content = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
                history_context += f"{role}: {content}\n"
            history_context += "\nUse this context to provide more relevant and personalized responses.\n"

        # Step 1: Rephrase the query based on chat history
        logger.debug(f"Original User message for general_platform_support_tool: {user_message}")
        if len(user_message.split()) < 4:
            rephrased_query = await rephrase_query_with_history(user_message, current_chat_history)
        else:
            rephrased_query = user_message
        logger.debug(f"Rephrased User message for general_platform_support_tool tool: {rephrased_query}")

        # Step 2: Query Qdrant with SentenceTransformer embeddings
        logger.info(f"Querying Qdrant with SentenceTransformer for: {rephrased_query}")
        qdrant_results = await query_qdrant_with_sentence_transformer(rephrased_query, limit=5, threshold=0.6)

        # Step 3: Build enhanced context from Qdrant results
        user_name = "Guest"
        if user_context and not request_context.is_anonymous:
            user_name = user_context.get('profile', {}).get('firstName', 'User')

        knowledge_context = f"User's name: {user_name}\n\n"

        if qdrant_results:
            knowledge_context += "\n\nRELEVANT KNOWLEDGE BASE INFORMATION (from semantic search):\n"
            for i, result in enumerate(qdrant_results, 1):
                logger.debug(f"general_platform_support_tool: Processing result {i}: {result}")
                knowledge_context += f" Content: {result.get('text')}\n"
        else:
            knowledge_context += "\nNo specific knowledge base results found with semantic search. Providing general guidance.\n"

        # Build system message
        system_message = f"""
You are a knowledgeable customer support agent for the Karmayogi Bharat learning platform.

{knowledge_context}

{history_context}

INSTRUCTIONS:
- Use the semantic search results above to provide accurate, detailed responses
- The similarity scores indicate relevance (higher = more relevant)
- Reference specific information from the knowledge base when available
- Provide step-by-step guidance when appropriate
- Be professional, clear, and actionable
- Use conversation history to avoid repetition and provide contextual responses
- If knowledge base info is insufficient, supplement with general platform knowledge
- Give complete answers based on available information rather than asking for clarification
- Do NOT ask follow-up questions or provide multiple choice options
- For user-specific queries, redirect to their personal dashboard

Your capabilities:
1. Platform features and functionality explanations
2. Technical troubleshooting guidance  
3. Navigation and usage help
4. Policy and procedure clarification
5. General course/event information (not user-specific)

Provide a comprehensive, helpful response based on all available information WITHOUT asking clarifying questions.
"""

        # Generate response using Gemini API
        logger.debug(f"general_platform_support_tool: system_message: {system_message}")
        response = await call_gemini_api(system_message)

        # Fallback to local LLM if Gemini fails
        if not response:
            logger.warning("Gemini API failed, falling back to local LLM")
            response = await call_local_llm(system_message, rephrased_query)
            logger.debug(f"general_platform_support_tool:: LOCAL LLM response: {response}")

        # Final fallback
        if not response:
            if qdrant_results:
                response = f"""Based on semantic search results for "{rephrased_query}":

{knowledge_context}

For additional assistance, please check the platform documentation or contact support."""
            else:
                response = f"""I understand you're asking about: {rephrased_query}

While I don't have specific documentation available right now, I can provide general guidance about the Karmayogi Bharat platform.

{history_context}

For the most accurate information, please:
1. Check the platform's help section
2. Contact technical support
3. Refer to the user documentation

Is there a specific aspect I can help clarify?"""

        logger.info(f"Enhanced response generated using {len(qdrant_results)} SentenceTransformer results")

        return {
            "success": True,
            "response": response,
            "query_type": "general_support_sentence_transformer",
            "original_query": user_message,
            "rephrased_query": rephrased_query,
            "knowledge_results_count": len(qdrant_results),
            "semantic_scores": [r.get("score", 0.0) for r in qdrant_results],
            "used_chat_history": len(current_chat_history) > 0,
            "embedding_model": EMBEDDING_MODEL_NAME
        }

    except Exception as e:
        logger.error(f"Error in SentenceTransformer enhanced general_platform_support_tool: {e}")
        return {
            "success": False,
            "error": str(e),
            "fallback_response": "I apologize, but I'm experiencing technical difficulties with the knowledge base. Please try your request again or contact support for assistance."
        }


# Legacy wrapper
async def general_platform_support_tool(user_message: str) -> dict:
    """Legacy wrapper - should be replaced with context version"""
    logger.error("Using legacy general_platform_support_tool without context - THIS CAUSES THREAD SAFETY ISSUES")
    return {"success": False, "error": "Context required for thread safety"}


async def query_qdrant_with_sentence_transformer(query: str, limit: int = 5, threshold: float = 0.6):
    """Query Qdrant using SentenceTransformer embeddings"""
    try:
        from main import generate_embeddings, qdrant_client

        query_embeddings = await generate_embeddings([query])
        query_vector = query_embeddings[0]

        if not isinstance(query_vector, list) or not all(isinstance(x, (int, float)) for x in query_vector):
            logger.error(f"Invalid query_vector format: {type(query_vector)}")
            raise ValueError("Query vector must be a flat list of floats")

        search_result = qdrant_client.search(
            collection_name="igot_docs",
            query_vector=query_vector,
            limit=limit,
            score_threshold=threshold
        )

        results = []
        for point in search_result:
            result = {
                "id": point.id,
                "score": point.score,
                "title": point.payload.get("title", "Untitled"),
                "content": point.payload.get("content", ""),
                "category": point.payload.get("category", "General"),
                "tags": point.payload.get("tags", []),
                **point.payload
            }
            results.append(result)

        logger.info(f"SentenceTransformer search returned {len(results)} results")
        return results

    except Exception as e:
        logger.error(f"Error querying Qdrant with SentenceTransformer: {e}")
        return await fallback_text_search(query, limit)


async def fallback_text_search(query: str, limit: int = 5):
    """Fallback text-based search when semantic search fails"""
    try:
        from main import qdrant_client
        from qdrant_client import models

        search_result, _ = qdrant_client.scroll(
            collection_name="igot_docs",
            scroll_filter=models.Filter(
                should=[
                    models.FieldCondition(key="content", match=models.MatchText(text=query)),
                    models.FieldCondition(key="title", match=models.MatchText(text=query))
                ]
            ),
            limit=limit
        )

        results = []
        for point in search_result:
            result = {
                "id": point.id,
                "score": 0.5,
                "title": point.payload.get("title", "Untitled"),
                "content": point.payload.get("content", ""),
                "category": point.payload.get("category", "General"),
                "tags": point.payload.get("tags", []),
                **point.payload
            }
            results.append(result)

        logger.info(f"Fallback text search returned {len(results)} results")
        return results

    except Exception as e:
        logger.error(f"Fallback text search also failed: {e}")
        return []


def create_generic_sub_agent(opik_tracer, request_context: RequestContext) -> Agent:
    """Create the generic sub-agent with request context (THREAD-SAFE)"""

    # Create tools that will receive context as parameter
    def make_tool_with_context(tool_func):
        """Wrapper to inject request context into tools"""

        async def wrapped_tool(user_message: str) -> dict:
            return await tool_func(user_message, request_context)

        wrapped_tool.__name__ = tool_func.__name__
        return wrapped_tool

    tools = [make_tool_with_context(general_platform_support_tool_with_context)]

    # Build chat history context for LLM
    history_context = ""
    chat_history = request_context.chat_history or []
    if chat_history:
        history_context = "\n\nRECENT CONVERSATION HISTORY:\n"
        for msg in chat_history[-6:]:
            role = "User" if msg.role == "user" else "Assistant"
            content = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
            history_context += f"{role}: {content}\n"

    user_name = "Guest"
    if request_context.user_context and not request_context.is_anonymous:
        user_name = request_context.user_context.get('profile', {}).get('firstName', 'User')

    agent = Agent(
        name="generic_sub_agent",
        model="gemini-2.0-flash-001",
        description="Specialized agent for handling general platform queries and support",
        instruction=f"""
You are a specialized sub-agent that handles general platform queries about:
- Platform features and functionality
- Technical troubleshooting
- Navigation and usage help
- General course/event information (not user-specific)
- Policies and procedures

IMPORTANT BEHAVIORAL RULES:
- DO NOT greet the user or say hello
- DO NOT use the user's name unless absolutely necessary for context  
- Get straight to answering the query
- Be direct and concise
- Focus only on providing the requested information or assistance

Use the general_platform_support_tool to provide comprehensive support.
The tool has access to conversation history to provide contextual responses.

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