# agents/generic_sub_agent.py
import logging
from typing import Dict, List
from google.adk.agents import Agent
from opik import track

logger = logging.getLogger(__name__)


@track(name="general_platform_support_tool")
async def general_platform_support_tool(user_message: str) -> dict:
    try:
        # Import global variables from main module
        from main import (
            current_chat_history, user_context, _rephrase_query_with_history,
            _call_gemini_api, _call_local_llm, query_qdrant_with_fastembed,
            FASTEMBED_MODEL
        )

        # Build chat history context
        history_context = ""
        if current_chat_history:
            history_context = "\n\nRECENT CONVERSATION HISTORY:\n"
            for msg in current_chat_history[-6:]:  # Last 3 exchanges
                role = "User" if msg.role == "user" else "Assistant"
                content = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
                history_context += f"{role}: {content}\n"
            history_context += "\nUse this context to provide more relevant and personalized responses.\n"

        # Step 1: Rephrase the query based on chat history
        print(f"Original User message for general_platform_support_tool: {user_message}")
        # if user_message_lower has less than 6 words, rephrase it
        if len(user_message.split()) < 4:
            rephrased_query = await _rephrase_query_with_history(user_message, current_chat_history)
        else:
            rephrased_query = user_message
        print(f"Rephrased User message for general_platform_support_tool tool: {rephrased_query}")

        # Step 2: Query Qdrant with FastEmbed embeddings
        logger.info(f"Querying Qdrant with FastEmbed for: {rephrased_query}")
        qdrant_results = await query_qdrant_with_fastembed(rephrased_query, limit=5, threshold=0.6)

        # Step 3: Build enhanced context from Qdrant results
        knowledge_context = "User's name: " + (
            user_context.get('profile', {}).get('firstName') if user_context else "Unknown") + "\n\n"
        if qdrant_results:
            knowledge_context = "\n\nRELEVANT KNOWLEDGE BASE INFORMATION (from semantic search):\n"
            for i, result in enumerate(qdrant_results, 1):
                title = result.get("title", "Untitled")
                content = result.get("content", "")
                category = result.get("category", "General")
                score = result.get("score", 0.0)
                tags = ", ".join(result.get("tags", []))

                # Limit content length
                content_preview = content[:400] + "..." if len(content) > 400 else content

                knowledge_context += f"\n{i}. [{category}] {title} (Similarity: {score:.3f})\n"
                if tags:
                    knowledge_context += f"   Tags: {tags}\n"
                knowledge_context += f"   Content: {content_preview}\n"

            knowledge_context += f"\nFound {len(qdrant_results)} highly relevant results using semantic search.\n"
        else:
            knowledge_context = "\n\nNo specific knowledge base results found with semantic search. Providing general guidance.\n"

        # Step 4: Create comprehensive system message
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
- For user-specific queries, redirect to their personal dashboard

Your capabilities:
1. Platform features and functionality explanations
2. Technical troubleshooting guidance  
3. Navigation and usage help
4. Policy and procedure clarification
5. General course/event information (not user-specific)

Provide a comprehensive, helpful response based on all available information.
"""

        # Step 5: Generate response using Gemini API
        print(f"general_platform_support_tool: system_message: {system_message}")
        response = await _call_gemini_api(system_message)

        # Fallback to local LLM if Gemini fails
        if not response:
            logger.warning("Gemini API failed, falling back to local LLM")
            response = await _call_local_llm(system_message, rephrased_query)
            print(f"general_platform_support_tool:: LOCAL LLM response: {response}")

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

        logger.info(f"Enhanced response generated using {len(qdrant_results)} FastEmbed results")

        return {
            "success": True,
            "response": response,
            "query_type": "general_support_fastembed",
            "original_query": user_message,
            "rephrased_query": rephrased_query,
            "knowledge_results_count": len(qdrant_results),
            "semantic_scores": [r.get("score", 0.0) for r in qdrant_results],
            "used_chat_history": len(current_chat_history) > 0,
            "embedding_model": FASTEMBED_MODEL
        }

    except Exception as e:
        logger.error(f"Error in FastEmbed enhanced general_platform_support_tool: {e}")
        return {
            "success": False,
            "error": str(e),
            "fallback_response": "I apologize, but I'm experiencing technical difficulties with the knowledge base. Please try your request again or contact support for assistance."
        }


def create_generic_sub_agent(opik_tracer, current_chat_history, user_context) -> Agent:
    """Create the generic sub-agent for general platform support"""

    tools = [general_platform_support_tool]

    # Build chat history context for LLM
    history_context = ""
    if current_chat_history:
        history_context = "\n\nRECENT CONVERSATION HISTORY:\n"
        for msg in current_chat_history[-6:]:  # Last 3 exchanges (6 messages)
            role = "User" if msg.role == "user" else "Assistant"
            content = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
            history_context += f"{role}: {content}\n"
        history_context += "\nUse this context to provide more relevant and personalized responses.\n"

    user_name = user_context.get('profile', {}).get('firstName', 'User') if user_context else 'User'

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

Use the general_platform_support_tool to provide comprehensive support for these types of queries.
The tool has access to conversation history to provide contextual responses.
Always be helpful and provide actionable guidance.

User's name: {user_name}

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