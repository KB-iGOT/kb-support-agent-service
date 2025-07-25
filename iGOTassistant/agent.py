

"""
Agent service implementation for the Karmayogi Bharat chatbot.
"""

import os
import logging

from dotenv import load_dotenv

from google.adk import Agent
from google.adk.tools import FunctionTool
# opik integration.
from opik.integrations.adk import OpikTracer
import opik
from .tools.tools import answer_course_event_questions
from .tools.tools import get_combined_user_details_clean_tool
from .tools.tools import get_account_creation_date_tool
from .tools.tools import get_user_group_tool
from .tools.tools import check_course_completion_status_tool
from .tools.tools import get_course_progress_tool
from .tools.tools import update_email_tool

from .models.callbacks import before_tool

from .config.config import LLM_CONFIG
from .prompt import INSTRUCTION, GLOBAL_INSTRUCTION
from .tools.userinfo_tools import validate_user, load_details_for_registered_users, update_name
from .tools.cert_tools import (
        handle_issued_certificate_issues,
        list_pending_contents,
        handle_certificate_qr_issues,
        handle_certificate_name_issues,
        )
from .tools.otp_auth_tools import send_otp, verify_otp
from .tools.zoho_ticket_tools import create_support_ticket_tool
from .tools.faq_tools import answer_general_questions
from .tools.tools import (

    update_phone_number_tool,
)

logger = logging.getLogger(__name__)
load_dotenv()

opik.configure(url=os.getenv("OPIK_URL"), use_local=True)
opik_tracer = OpikTracer(project_name=os.getenv("OPIK_PROJECT"))

# agent = Agent(
#     model=os.getenv("GEMINI_MODEL"),
#     name="iGotAssistant",
#     generate_content_config=LLM_CONFIG,
#     instruction=INSTRUCTION,
#     global_instruction=GLOBAL_INSTRUCTION,
#     tools=[
#         validate_user,
#         load_details_for_registered_users,
#         answer_general_questions,
#         create_support_ticket_tool,
#         handle_issued_certificate_issues,
#         send_otp,
#         verify_otp,
#         update_phone_number_tool,
#         update_name,
#         list_pending_contents,
#         handle_certificate_qr_issues,
#         handle_certificate_name_issues,
#     ],
#     before_agent_callback=opik_tracer.before_agent_callback,
#     after_agent_callback=opik_tracer.after_agent_callback,
#     before_model_callback=opik_tracer.before_model_callback,
#     after_model_callback=opik_tracer.after_model_callback,
#     before_tool_callback=opik_tracer.before_tool_callback,
#     after_tool_callback=opik_tracer.after_tool_callback,

# )

root_agent = Agent(
    model=os.getenv("GEMINI_MODEL"),
    description="You are a helpful assistant that can answer learning platform related conversations.",
    # model=LiteLlm(os.getenv("OLLAMA_MODEL")),
    name="iGOTAssistant",
    generate_content_config=LLM_CONFIG,
    instruction=INSTRUCTION,
    # include_contents='none',
    global_instruction=GLOBAL_INSTRUCTION,
    tools=[

        FunctionTool(get_combined_user_details_clean_tool),

        FunctionTool(answer_general_questions),
        FunctionTool(answer_course_event_questions),
        FunctionTool(create_support_ticket_tool),
        FunctionTool(handle_issued_certificate_issues),
        FunctionTool(send_otp),
        FunctionTool(verify_otp),
        FunctionTool(update_phone_number_tool),
        FunctionTool(update_email_tool),
        FunctionTool(list_pending_contents),
        FunctionTool(handle_certificate_name_issues),
        FunctionTool(handle_certificate_qr_issues),
        FunctionTool(update_name),
        FunctionTool(get_account_creation_date_tool),
        FunctionTool(get_user_group_tool),
        FunctionTool(check_course_completion_status_tool),
        FunctionTool(get_course_progress_tool),

    ],
    before_agent_callback=opik_tracer.before_agent_callback,
    after_agent_callback=opik_tracer.after_agent_callback,
    before_model_callback=opik_tracer.before_model_callback,
    after_model_callback=opik_tracer.after_model_callback,
    before_tool_callback=opik_tracer.before_tool_callback,
    after_tool_callback=opik_tracer.after_tool_callback,
)

# agent = Agent(
#     model=os.getenv("GEMINI_MODEL"),
#     name="iGotAssistant",
#     generate_content_config=LLM_CONFIG,
#     instruction=INSTRUCTION,
#     global_instruction=GLOBAL_INSTRUCTION,
#     tools=[
#         validate_user,
#         load_details_for_registered_users,
#         answer_general_questions,
#         create_support_ticket_tool,
#         handle_issued_certificate_issues,
#         send_otp,
#         verify_otp,
#         update_phone_number_tool,
#         update_name,
#         list_pending_contents,
#         handle_certificate_qr_issues,
#         handle_certificate_name_issues,
#     ],
#     before_agent_callback=opik_tracer.before_agent_callback,
#     after_agent_callback=opik_tracer.after_agent_callback,
#     before_model_callback=opik_tracer.before_model_callback,
#     after_model_callback=opik_tracer.after_model_callback,
#     before_tool_callback=opik_tracer.before_tool_callback,
#     after_tool_callback=opik_tracer.after_tool_callback,

# )
