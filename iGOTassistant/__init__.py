"""
Loading Google agent and needed envs. 
"""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import the agent based on the environment
try:
    from .agent import root_agent
    # For ADK web compatibility
    agent = root_agent
except ImportError:
    # Fallback for uvicorn or other environments
    try:
        from .agent_fastapi import ChatAgent
        chat_agent = ChatAgent()
        agent = chat_agent.agent
    except ImportError:
        agent = None

# Export the agent for both ADK web and uvicorn
__all__ = ['agent', 'root_agent']
