"""
Loading Google agent and needed envs. 
"""
import logging
import sys
import os
from dotenv import load_dotenv


# from .agent import agent as root_agent
# from .agent import agent # as root_agent
from .tools.faq_tools import (
    initialize_environment,
    initialize_knowledge_base,
    answer_general_questions
)

load_dotenv()

def initialize_env():
    """trying laod env before agent starts"""
    try:
        initialize_environment()
        KB_AUTH_TOKEN = os.getenv('KB_AUTH_TOKEN')
        KB_DIR = initialize_knowledge_base()
        response = answer_general_questions("What is karma points?")
        print(response)
        logging.info("Knowledge base initialized successfully.")
        # return queryengine
    except (ValueError, FileNotFoundError, ImportError, RuntimeError) as e:
        logging.info("Error initializing knowledge base: %s", e)
        sys.exit(1)

    logging.info("✅ Successfully initialized tools and knowledge base")

initialize_env()

from .agent import agent as root_agent