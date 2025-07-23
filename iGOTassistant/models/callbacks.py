"""

Verify the user profile before every tool calls.

"""


from google.adk.agents.callback_context import CallbackContext

from google.adk.tools import BaseTool


from typing import Any, Dict, Optional, Tuple



def before_tool( tool: BaseTool,
                args: Dict[str, Any],
                tool_context: CallbackContext
        ):
    print(f'@{tool.name}')
    # if tool.name is not "answer_general_questions":
    #     if "user_id" not in args and "user_id" not in tool_context.state:
    #         return "You need to authenticate for this service"
    #     print(tool_context.state)
    #     print(f" Calling: ----------------  {tool.name}")
    #     print(f"Args: {args}")
    #         print(f'tool context: {tool_context}')
