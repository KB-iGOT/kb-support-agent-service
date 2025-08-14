# agents/anonymous_ticket_support_sub_agent.py
import logging
import os

from google.adk.agents import Agent
from utils.request_context import RequestContext

logger = logging.getLogger(__name__)

SUPPORT_TEAMS_LINK=os.getenv("SUPPORT_TEAMS_LINK", "https://teams.microsoft.com/l/meetup-join/19%3ameeting_M2Y3ZDE2ZDMtMWQwYS00OWQzLWE3NDctNDRkNTdjOGI4Yzll%40thread.v2/0?context=%7b%22Tid%22%3a%2240cfb65c-9b71-435f-8bc2-bc2c69df1aca%22%2c%22Oid%22%3a%22cbd37bc9-5c33-401f-b590-9decb3c370f8%22%7d")
SUPPORT_EMAIL_ID=os.getenv("SUPPORT_EMAIL_ID", "mission.karmayogi@gov.in")

async def provide_support_information(user_message: str, request_context: RequestContext) -> dict:
    """
    Provide support information based on knowledge base search.
    Does NOT create any tickets - just returns helpful information or directs to support.
    """
    try:
        if not request_context:
            return {"success": False, "error": "Request context not available"}

        print(f"Searching knowledge base for: {user_message}")

        # Get context data from request_context
        current_chat_history = request_context.chat_history or []
        user_context = request_context.user_context or {}

        # Import functions locally to avoid global state issues
        from utils.common_utils import rephrase_query_with_history, call_gemini_api, call_local_llm

        # Build chat history context
        history_context = ""
        if current_chat_history:
            history_context = "\n\nRECENT CONVERSATION HISTORY:\n"
            for msg in current_chat_history[-6:]:
                role = "User" if msg.role == "user" else "Assistant"
                content = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
                history_context += f"{role}: {content}\n"

        # Step 1: Rephrase the query based on chat history
        print(f"Original user message: {user_message}")
        if len(user_message.split()) < 4:
            rephrased_query = await rephrase_query_with_history(user_message, current_chat_history)
        else:
            rephrased_query = user_message
        print(f"Rephrased query: {rephrased_query}")

        # Step 2: Query Qdrant with SentenceTransformer embeddings
        print(f"Querying knowledge base for: {rephrased_query}")
        qdrant_results = await query_qdrant_with_sentence_transformer(rephrased_query, limit=5, threshold=0.7)

        # Step 3: Build response based on search results
        user_name = "Guest"
        if user_context and not request_context.is_anonymous:
            user_name = user_context.get('profile', {}).get('firstName', 'User')

        # Check if we have relevant results
        if qdrant_results and len(qdrant_results) > 0:
            # We have relevant information - provide helpful response
            knowledge_context = f"User's name: {user_name}\n\n"
            knowledge_context += "RELEVANT INFORMATION:\n"
            for i, result in enumerate(qdrant_results, 1):
                logger.debug(f"Processing result {i}: {result}")
                knowledge_context += f"- {result.get('text', '')}\n"

            # Build system message for generating helpful response
            system_message = f"""
You are a helpful customer support assistant for the Karmayogi Bharat learning platform.

{knowledge_context}

{history_context}

INSTRUCTIONS:
- Use the relevant information above to provide a helpful, accurate response
- Provide step-by-step guidance when appropriate
- Be professional, clear, and actionable
- Use conversation history to provide contextual responses
- Give complete answers based on available information
- Do NOT mention creating tickets or support tickets
- If the information partially helps, provide what you can and suggest contacting support for additional help

CRITICAL: End your response with: "For additional assistance, please contact us between 9 AM to 5 PM from Monday to Friday on Teams link [{SUPPORT_TEAMS_LINK}] or email us [{SUPPORT_EMAIL_ID}]"

Provide a comprehensive, helpful response based on the available information.
"""

            print(f"System message: {system_message}")
            response = await call_gemini_api(system_message)

            # Fallback to local LLM if Gemini fails
            if not response:
                print("Gemini API failed, falling back to local LLM")
                response = await call_local_llm(system_message, rephrased_query)

            if response:
                return {
                    "success": True,
                    "response": response,
                    "has_relevant_info": True,
                    "knowledge_results_count": len(qdrant_results),
                    "used_chat_history": len(current_chat_history) > 0
                }

        # No relevant results found - provide fallback message
        fallback_response = f"I do not have relevant information for your query. Please contact the support team on Teams at [{SUPPORT_TEAMS_LINK}] (Monday-Friday, 9 AM to 5 PM) or email {SUPPORT_EMAIL_ID}"

        return {
            "success": True,
            "response": fallback_response,
            "has_relevant_info": False,
            "knowledge_results_count": len(qdrant_results) if qdrant_results else 0,
            "used_chat_history": len(current_chat_history) > 0
        }

    except Exception as e:
        logger.error(f"Error in support information lookup: {e}")
        fallback_response = f"I do not have relevant information for your query. Please contact the support team on Teams at [{SUPPORT_TEAMS_LINK}] (Monday-Friday, 9 AM to 5 PM) or email {SUPPORT_EMAIL_ID}"

        return {
            "success": False,
            "error": str(e),
            "response": fallback_response,
            "has_relevant_info": False
        }


async def query_qdrant_with_sentence_transformer(query: str, limit: int = 5, threshold: float = 0.7):
    """Query Qdrant using SentenceTransformer embeddings"""
    try:
        from utils.common_utils import generate_embeddings, qdrant_client

        query_embeddings = await generate_embeddings([query])
        query_vector = query_embeddings[0]

        if not isinstance(query_vector, list) or not all(isinstance(x, (int, float)) for x in query_vector):
            print(f"Invalid query_vector format: {type(query_vector)}")
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
                "text": point.payload.get("text", point.payload.get("content", "")),
                **point.payload
            }
            results.append(result)

        print(f"Knowledge base search returned {len(results)} results above threshold {threshold}")
        return results

    except Exception as e:
        print(f"Error querying knowledge base: {e}")
        return []


def create_anonymous_ticket_support_sub_agent(opik_tracer, request_context: RequestContext) -> Agent:
    """
    Create a specialized sub-agent for providing support information to anonymous/guest users.
    Does NOT create tickets - only provides information or directs to support.
    """

    agent_instruction = f"""You are a helpful support assistant for anonymous/guest users of the Karmayogi Bharat platform.

USER STATUS: Anonymous/Guest User (Not Logged In)

🎯 PRIMARY GOAL: Provide helpful information based on knowledge base search, or direct users to contact support.

INSTRUCTIONS:
- When a user reports a problem or asks a question, use the provide_support_information tool
- Provide helpful information if available in the knowledge base
- If no relevant information is found, direct users to contact support
- Be empathetic and professional in your response
- Do NOT mention creating tickets or support tickets
- Do NOT claim to have created any tickets

WORKFLOW:
1. User asks question/reports issue → Use provide_support_information tool
2. If helpful info found → Provide clear, actionable guidance
3. If no relevant info found → Direct to support contact information

CRITICAL: Never claim to create tickets. Only provide information or direct to support contact.
"""

    print(f"Creating anonymous support agent (no ticket creation) with request_context: {request_context}")

    # Create tools that will receive context as parameter
    def make_tool_with_context(tool_func):
        """Wrapper to inject request context into tools"""

        async def wrapped_tool(user_message: str) -> dict:
            return await tool_func(user_message, request_context)

        wrapped_tool.__name__ = tool_func.__name__
        return wrapped_tool

    tools = [make_tool_with_context(provide_support_information)]

    print("Creating anonymous support agent with knowledge-base-only tools:", tools)

    return Agent(
        name="anonymous_support_information_agent",
        model="gemini-2.0-flash-001",
        description="Provides support information to anonymous users based on knowledge base",
        instruction=agent_instruction,
        tools=tools,
        before_agent_callback=opik_tracer.before_agent_callback,
        after_agent_callback=opik_tracer.after_agent_callback,
        before_model_callback=opik_tracer.before_model_callback,
        after_model_callback=opik_tracer.after_model_callback,
    )