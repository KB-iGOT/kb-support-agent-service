"""
Agent service implementation for the Karmayogi Bharat chatbot.
"""

import logging
import os
import sys
import time

import opik
import coloredlogs

from dotenv import load_dotenv
from google.adk import Agent
from google.adk import Runner
from google.adk.artifacts import InMemoryArtifactService
from google.adk.events import Event, EventActions
from google.adk.sessions import DatabaseSessionService
from google.genai import types
from opik.integrations.adk import OpikTracer
from google.adk.tools import FunctionTool
from google.cloud import aiplatform
from google.adk.models.lite_llm import LiteLlm
import json



from .config.config import LLM_CONFIG
from .models.chat import Request
from .prompt import INSTRUCTION, GLOBAL_INSTRUCTION
from .tools.cert_tools import (
    handle_issued_certificate_issues,
    list_pending_contents,
    handle_certificate_qr_issues,
    handle_certificate_name_issues,
)
from .tools.faq_tools import (
    answer_general_questions,
    initialize_environment,
    initialize_knowledge_base
)
from .tools.otp_auth_tools import send_otp, verify_otp
from .tools.tools import (
    update_phone_number_tool,
    get_combined_user_details_tool,
    answer_course_event_questions
)
from .tools.userinfo_tools import fetch_userdetails, load_details_for_registered_users, update_name
from .tools.zoho_ticket_tools import create_support_ticket_tool


def configure_logging():
    coloredlogs.DEFAULT_FIELD_STYLES["levelname"] = dict(color='green', bold=True)
    coloredlogs.install(
        level='INFO',
        fmt="%(asctime)s : %(filename)s : %(funcName)s : %(levelname)s : %(message)s")

configure_logging()
logger = logging.getLogger("iGOT")

opik.configure(url=os.getenv("OPIK_URL"), use_local=True)
opik_tracer = OpikTracer(project_name=os.getenv("OPIK_PROJECT"))

# Tool timing tracking for conversation turns
class ToolTimingTracker:
    def __init__(self):
        self.tool_timings = {}
        self.current_user_id = None
    
    def start_tool(self, tool_name: str, user_id: str):
        """Start timing a tool execution."""
        self.current_user_id = user_id
        self.tool_timings[tool_name] = {
            'start_time': time.time(),
            'user_id': user_id
        }
        logger.info(f"🔧 [{user_id}] Tool execution started: {tool_name}")
    
    def end_tool(self, tool_name: str, user_id: str):
        """End timing a tool execution and log duration."""
        if tool_name in self.tool_timings and self.tool_timings[tool_name]['user_id'] == user_id:
            end_time = time.time()
            duration = end_time - self.tool_timings[tool_name]['start_time']
            logger.info(f"✅ [{user_id}] Tool {tool_name} completed in {duration:.2f}s")
            
            # Performance warning for slow tools
            if duration > 5.0:
                logger.warning(f"⚠️ [{user_id}] Slow tool {tool_name}: {duration:.2f}s")
            
            # Store timing for summary
            self.tool_timings[tool_name]['end_time'] = end_time
            self.tool_timings[tool_name]['duration'] = duration
            return duration
        return None
    
    def get_tool_summary(self, user_id: str):
        """Get summary of tools executed for a user."""
        user_tools = {name: data for name, data in self.tool_timings.items() 
                     if data.get('user_id') == user_id and 'duration' in data}
        return user_tools
    
    def clear_user_tools(self, user_id: str):
        """Clear tool timings for a specific user."""
        self.tool_timings = {name: data for name, data in self.tool_timings.items() 
                           if data.get('user_id') != user_id}

# Global tool timing tracker
tool_tracker = ToolTimingTracker()

def before_tool_callback_with_timing(tool, tool_args):
    """Enhanced callback to track tool execution start time."""
    try:
        tool_name = tool.name if hasattr(tool, 'name') else str(tool)
        # Extract user_id from tool_args or context if available
        user_id = "unknown"
        if isinstance(tool_args, dict):
            user_id = tool_args.get('user_id', 'unknown')
        elif hasattr(tool_args, 'state') and hasattr(tool_args.state, 'get'):
            user_id = tool_args.state.get('user_id', 'unknown')
        
        tool_tracker.start_tool(tool_name, user_id)
        
        # Call the original opik tracer callback
        if hasattr(opik_tracer, 'before_tool_callback'):
            return opik_tracer.before_tool_callback(tool, tool_args)
    except Exception as e:
        logger.error(f"Error in before_tool_callback_with_timing: {e}")

def after_tool_callback_with_timing(tool, tool_result):
    """Enhanced callback to track tool execution end time."""
    try:
        tool_name = tool.name if hasattr(tool, 'name') else str(tool)
        # Try to get user_id from the tool result or context
        user_id = "unknown"
        if hasattr(tool_result, 'state') and hasattr(tool_result.state, 'get'):
            user_id = tool_result.state.get('user_id', 'unknown')
        elif isinstance(tool_result, dict):
            user_id = tool_result.get('user_id', 'unknown')
        
        tool_tracker.end_tool(tool_name, user_id)
        
        # Call the original opik tracer callback
        if hasattr(opik_tracer, 'after_tool_callback'):
            return opik_tracer.after_tool_callback(tool, tool_result)
    except Exception as e:
        logger.error(f"Error in after_tool_callback_with_timing: {e}")


def initialize_env():
    """trying laod env before agent starts"""
    try:
        initialize_environment()
        KB_AUTH_TOKEN = os.getenv('KB_AUTH_TOKEN')
        KB_DIR = initialize_knowledge_base()
        response = answer_general_questions("What is karma points?")
        logger.info(response)
    except (ValueError, FileNotFoundError, ImportError, RuntimeError) as e:
        logger.info("Error initializing knowledge base: %s", e)
        sys.exit(1)

    logger.info("✅ Successfully initialized tools and knowledge base")




# Note: CourseAgent has been replaced with answer_course_event_questions tool
# which uses Ollama directly to answer course and event questions using Redis user data

class ChatAgent:
    """
    ChatAgent class to manage chat sessions and interactions with the Gemini model.
    """
    app_name = "iGOTAssitant"
    agent = None
    user_id = None
    session_service = DatabaseSessionService(db_url=os.getenv("POSTGRES_URL"))
    artifact_service = InMemoryArtifactService()
    runner = None
    session = None

    def __init__(self):
        load_dotenv()
        self.chat_sessions = {}

    
        logger.info("Initializing Google ADK agent")
        self.agent = Agent(
            model=os.getenv("GEMINI_MODEL"),
            description="You are a helpful assistant that can answer learning platform related conversations.",
            # model=LiteLlm(os.getenv("OLLAMA_MODEL")),
            name="iGOTAssistant",
            generate_content_config=LLM_CONFIG,
            instruction=INSTRUCTION,
            # include_contents='none',
            global_instruction=GLOBAL_INSTRUCTION,
            tools=[
                FunctionTool(get_combined_user_details_tool),
                # FunctionTool(fetch_userdetails),
                # FunctionTool(load_details_for_registered_users),
                FunctionTool(answer_general_questions),
                FunctionTool(answer_course_event_questions),
                FunctionTool(create_support_ticket_tool),
                FunctionTool(handle_issued_certificate_issues),
                FunctionTool(send_otp),
                FunctionTool(verify_otp),
                FunctionTool(update_phone_number_tool),
                FunctionTool(list_pending_contents),
                FunctionTool(handle_certificate_name_issues),
                FunctionTool(handle_certificate_qr_issues),
                FunctionTool(update_name),
                # FunctionTool(generate_with_vertex_cache)
                # transfer_to_agent,
            ],
            before_agent_callback=opik_tracer.before_agent_callback,
            after_agent_callback=opik_tracer.after_agent_callback,
            before_model_callback=opik_tracer.before_model_callback,
            after_model_callback=opik_tracer.after_model_callback,
            before_tool_callback=opik_tracer.before_tool_callback,
            after_tool_callback=opik_tracer.after_tool_callback,
        )

        self.runner = Runner(app_name=self.app_name, 
                            agent=self.agent, session_service=self.session_service,
                            artifact_service=self.artifact_service)
        logger.info("ChatAgent initialized")

    async def start_new_session(self, user_id, session_id: str) -> dict:
        """Start a new chat session with initial instructions."""
        # logger.info(f'{user_id} :: Trying to start new session {request.session_id}')

        if await self.session_service.get_session(app_name=self.app_name, session_id=session_id, user_id=user_id):
            return {"message" : "Session exist, try chat send."}

        # logger.info(f'{user_id} :: Session id', request.session_id)
        self.user_id = user_id,
        self.session = await self.session_service.create_session(
                app_name=self.app_name,
                session_id=session_id ,
                user_id=user_id
                )

        return {"message": "Starting new chat session."}

    async def send_message(self, user_id, request: Request, session_id: str) -> dict:
        """Send a message in an existing chat session."""
        
        # Start timing the complete conversation turn
        conversation_start_time = time.time()
        logger.info(f"🕐 [{user_id}] Starting conversation turn for session {session_id}")
        logger.info(f"📝 [{user_id}] User message: {request.text[:100]}{'...' if len(request.text) > 100 else ''}")
        
        response = ""
        audio_url = None
        # MAX_CONTEXT_EVENTS = 5

        if not request.text:
            raise ValueError("Request text cannot be empty.")
        
        content = types.Content(
            role='user',
            parts=[types.Part.from_text(text=request.text)]
        )


        # Time session management
        session_start_time = time.time()
        logger.info(f"🔗 [{user_id}] Checking session status")
        
        if not await self.runner.session_service.get_session(app_name=self.app_name, user_id=user_id, session_id=session_id):
            logger.info(f"🆕 [{user_id}] Creating new session")
            await self.start_new_session(user_id, session_id)

        # If the user is on the web channel, mark them as authenticated in the session context
        if request.channel_id == "web" or request.channel_id == "app": 
            logger.info(f"🌐 [{user_id}] Processing web/app channel authentication")
            # You may need to adjust how context is set depending on your ADK version
            session = await self.runner.session_service.get_session(
                app_name=self.app_name, user_id=user_id, session_id=session_id
            )

        

            if session is not None and not session.state.get("web", False):
                logger.info(f"{user_id} :: Setting the WEB ......")
                time_now = time.time()
                state_changes = {
                    "web" : True,
                    "user_id" : user_id,
                    "validuser" : True,
                    "otp_auth": True,
                    "loaded_details" : False
                }

                action_with_update = EventActions(state_delta=state_changes)
                system_event = Event(
                    invocation_id="inv_login_update",
                    author="iGOTAssistant", # Or 'agent', 'tool' etc.
                    actions=action_with_update,
                    timestamp=time_now,
                )

                await self.runner.session_service.append_event(session, system_event)
                logger.info(f"✅ [{user_id}] Web/app authentication completed")

            # logger.info(f'{user_id} :: Setting state', session.state.get("web"))
            # logger.info(f'{user_id} :: Setting user_id', session.state.get("user_id"))

        # End session management timing
        session_end_time = time.time()
        session_management_time = session_end_time - session_start_time
        logger.info(f"🔗 [{user_id}] Session management completed in {session_management_time:.2f}s")

        # Time the model execution
        model_start_time = time.time()
        logger.info(f"🤖 [{user_id}] Starting model execution")
        
        # Track tool executions during this conversation turn
        tools_executed = []
        tool_start_times = {}
        
        try:
            async for event in self.runner.run_async(
                    user_id=user_id,
                    session_id=session_id,
                    new_message=content):
                if event.is_final_response():
                    response = event.content.parts[0].text
                
                # Track tool executions by monitoring event types
                # Log any tool-related events for debugging
                if hasattr(event, 'type') and event.type:
                    logger.debug(f"🔍 [{user_id}] Event type: {event.type}")
                
                # Track function calls (tools) in content
                if event.content and hasattr(event.content, 'parts'):
                    for part in event.content.parts:
                        if hasattr(part, 'function_call') and part.function_call:
                            tool_name = part.function_call.name
                            if tool_name not in tools_executed:
                                tools_executed.append(tool_name)
                                tool_start_times[tool_name] = time.time()
                                logger.info(f"🔧 [{user_id}] Tool called: {tool_name}")
                
                # if event.content and getattr(event.content.parts[0], "function_call"):
                #     print(event.content.parts[0].function_call)
                if event.content:
                    print(event.content)
        except Exception as e:
            logger.error(f"❌ [{user_id}] Error during model execution: {str(e)}")
            model_end_time = time.time()
            conversation_end_time = time.time()
            logger.error(f"⏱️ [{user_id}] Model execution failed after {model_end_time - model_start_time:.2f}s")
            logger.error(f"⏱️ [{user_id}] Total conversation turn failed after {conversation_end_time - conversation_start_time:.2f}s")
            raise e

        # End timing for model execution
        model_end_time = time.time()
        model_execution_time = model_end_time - model_start_time
        logger.info(f"✅ [{user_id}] Model execution completed in {model_execution_time:.2f}s")

        # End timing for complete conversation turn
        conversation_end_time = time.time()
        total_conversation_time = conversation_end_time - conversation_start_time
        
        # Log comprehensive timing information
        logger.info(f"📊 [{user_id}] TIMING SUMMARY:")
        logger.info(f"   • Session management: {session_management_time:.2f}s")
        logger.info(f"   • Model execution: {model_execution_time:.2f}s")
        logger.info(f"   • Total conversation turn: {total_conversation_time:.2f}s")
        logger.info(f"   • Response length: {len(response) if response else 0} characters")
        
        # Log tool execution summary
        if tools_executed:
            logger.info(f"🔧 [{user_id}] TOOLS EXECUTED ({len(tools_executed)}):")
            for tool_name in tools_executed:
                if tool_name in tool_start_times:
                    tool_duration = time.time() - tool_start_times[tool_name]
                    logger.info(f"   • {tool_name}: {tool_duration:.2f}s")
                    
                    # Performance warning for slow tools
                    if tool_duration > 5.0:
                        logger.warning(f"⚠️ [{user_id}] Slow tool {tool_name}: {tool_duration:.2f}s")
        else:
            logger.info(f"🔧 [{user_id}] No tools executed in this turn")
        
        # Also check the global tool tracker for this user
        user_tools = tool_tracker.get_tool_summary(user_id)
        if user_tools:
            logger.info(f"🔧 [{user_id}] GLOBAL TOOL TRACKER SUMMARY:")
            for tool_name, tool_data in user_tools.items():
                duration = tool_data.get('duration', 0)
                logger.info(f"   • {tool_name}: {duration:.2f}s")
        
        # Clear tool timings for this user to prevent memory buildup
        tool_tracker.clear_user_tools(user_id)
        
        # Performance warnings
        if session_management_time > 2.0:
            logger.warning(f"⚠️ [{user_id}] Slow session management: {session_management_time:.2f}s")
        if model_execution_time > 10.0:
            logger.warning(f"⚠️ [{user_id}] Slow model execution: {model_execution_time:.2f}s")
        if total_conversation_time > 15.0:
            logger.warning(f"⚠️ [{user_id}] Slow conversation turn: {total_conversation_time:.2f}s")

        if response == "": 
            logger.error(f"❌ [{user_id}] Empty response received")
            return {"text": "Sorry, Something went wrong, try again later.", "audio": audio_url}
        
        logger.info(f"🎯 [{user_id}] Conversation turn completed successfully")
        return {"text": response, "audio": audio_url}

