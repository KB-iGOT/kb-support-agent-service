import os
import logging
from typing import Dict, List, Optional

from google.adk.agents import Agent
from opik import track

from utils.request_context import RequestContext
from utils.course_module_status_api import get_module_status_api_client
from utils.common_utils import call_gemini_api, call_local_llm
from utils.prompt_loader import get_prompt

logger = logging.getLogger(__name__)

OPIK_PROJECT = os.getenv("OPIK_PROJECT", "default")


def _normalize_text(s: str) -> str:
    return " ".join((s or "").lower().split())


@track(name="resolve_progress_target_tool", project_name=OPIK_PROJECT)
async def resolve_progress_target_tool(user_message: str, request_context: RequestContext = None) -> Dict:
    """
    Resolve whether the user refers to a course or an event and identify matching items from enrollments.

    Returns
    - success: bool
    - type: "course"|"event"
    - matches: list of {name, id, batch_id}
    - error: optional
    """
    try:
        if not request_context or not request_context.user_context:
            return {"success": False, "error": "User context not available"}

        message = user_message.strip()
        user_lower = message.lower()

        # Prefer explicit mention of type; otherwise infer using keywords
        target_type = "course"
        if " event" in f" {user_lower}" or "webinar" in user_lower:
            target_type = "event"
        if " course" in f" {user_lower}":
            target_type = "course"

        # Extract a potential name token by removing generic words
        # Fallback to using the full message
        query = message

        matches: List[Dict] = []
        if target_type == "course":
            enrollments = request_context.get_course_enrollments()
            for c in enrollments:
                name = c.get("course_name") or c.get("content", {}).get("name")
                cid = c.get("course_identifier") or c.get("courseId") or c.get("contentId")
                batch = c.get("course_batch_id") or c.get("batchId")
                if name and cid and (_normalize_text(query) in _normalize_text(name) or _normalize_text(name) in _normalize_text(query)):
                    matches.append({"name": name, "id": cid, "batch_id": batch})
        else:
            enrollments = request_context.get_event_enrollments()
            for e in enrollments:
                event = e.get("event", {})
                name = e.get("event_name") or event.get("name")
                eid = e.get("event_identifier") or event.get("identifier") or e.get("contentId")
                batch = e.get("event_batch_id") or e.get("batchId")
                if name and eid and (_normalize_text(query) in _normalize_text(name) or _normalize_text(name) in _normalize_text(query)):
                    matches.append({"name": name, "id": eid, "batch_id": batch})

        # If no matches, return list of all names to help disambiguate
        if not matches:
            catalog = []
            if target_type == "course":
                for c in request_context.get_course_enrollments():
                    name = c.get("course_name") or c.get("content", {}).get("name")
                    cid = c.get("course_identifier") or c.get("courseId") or c.get("contentId")
                    if name and cid:
                        catalog.append({"name": name, "id": cid, "batch_id": c.get("course_batch_id") or c.get("batchId")})
            else:
                for e in request_context.get_event_enrollments():
                    event = e.get("event", {})
                    name = e.get("event_name") or event.get("name")
                    eid = e.get("event_identifier") or event.get("identifier") or e.get("contentId")
                    if name and eid:
                        catalog.append({"name": name, "id": eid, "batch_id": e.get("event_batch_id") or e.get("batchId")})

            return {"success": True, "type": target_type, "matches": catalog, "note": "no_direct_match"}

        return {"success": True, "type": target_type, "matches": matches}

    except Exception as e:
        logger.error(f"Error in resolve_progress_target_tool: {e}")
        return {"success": False, "error": str(e)}


@track(name="get_course_progress_tool", project_name=OPIK_PROJECT)
async def get_course_progress_tool(user_message: str, request_context: RequestContext = None) -> Dict:
    """
    Fetch detailed course module status for the identified course.
    Expects the message to contain a course id in the form do_... or a course name present in enrollments.
    """
    try:
        if not request_context:
            return {"success": False, "error": "Missing request context"}

        # Try to resolve a course id from the message first
        course_id: Optional[str] = None
        msg = user_message
        tokens = msg.replace("\n", " ").split()
        for t in tokens:
            if t.startswith("do_"):
                course_id = t
                break

        if not course_id:
            # Match by name from enrollments
            resolution = await resolve_progress_target_tool(user_message, request_context)
            if not resolution.get("success"):
                return resolution
            if resolution.get("type") != "course":
                return {"success": False, "error": "Target resolved as event; use event progress tool"}
            matches = resolution.get("matches", [])
            if len(matches) == 1:
                course_id = matches[0]["id"]
            elif len(matches) > 1:
                # Let the agent ask user to choose
                return {
                    "success": True,
                    "action": "disambiguate",
                    "type": "course",
                    "options": [{"name": m["name"], "id": m["id"]} for m in matches]
                }
            else:
                return {
                    "success": False,
                    "error": "No matching course found in your enrollments. Please share the exact course name."
                }

        api = await get_module_status_api_client()
        details = await api.get_detailed_module_status(request_context.user_id, course_id)
        if not details:
            return {"success": False, "error": "Unable to fetch course module status right now."}

        return {"success": True, "type": "course", "details": details}

    except Exception as e:
        logger.error(f"Error in get_course_progress_tool: {e}")
        return {"success": False, "error": str(e)}


@track(name="get_event_progress_tool", project_name=OPIK_PROJECT)
async def get_event_progress_tool(user_message: str, request_context: RequestContext = None) -> Dict:
    """
    Fetch event completionPercentage for a given event (by id or name from enrollments).
    """
    try:
        if not request_context:
            return {"success": False, "error": "Missing request context"}

        # Extract event id if provided
        event_id: Optional[str] = None
        batch_id: Optional[str] = None
        msg = user_message
        tokens = msg.replace("\n", " ").split()
        for t in tokens:
            if t.startswith("do_"):
                event_id = t
                break

        if not event_id:
            resolution = await resolve_progress_target_tool(user_message, request_context)
            if not resolution.get("success"):
                return resolution
            if resolution.get("type") != "event":
                return {"success": False, "error": "Target resolved as course; use course progress tool"}
            matches = resolution.get("matches", [])
            if len(matches) == 1:
                event_id = matches[0]["id"]
                batch_id = matches[0].get("batch_id")
            elif len(matches) > 1:
                return {
                    "success": True,
                    "action": "disambiguate",
                    "type": "event",
                    "options": matches
                }
            else:
                return {"success": False, "error": "No matching event found in your enrollments."}

        # If batch_id wasn't found, try to discover from enrollments
        if not batch_id:
            for e in request_context.get_event_enrollments():
                ev = e.get("event", {})
                eid = e.get("event_identifier") or ev.get("identifier") or e.get("contentId")
                if eid == event_id:
                    batch_id = e.get("event_batch_id") or e.get("batchId")
                    break

        api = await get_module_status_api_client()
        result = await api.fetch_event_status(request_context.user_id, event_id, batch_id)
        if not result:
            return {"success": False, "error": "Unable to fetch event status right now."}

        # Get event name via content search
        name_map = await api.fetch_module_names([event_id])
        event_name = name_map.get(event_id, {}).get("name", "Unknown Event")

        return {
            "success": True,
            "type": "event",
            "details": {
                "event_id": event_id,
                "event_name": event_name,
                **result
            }
        }

    except Exception as e:
        logger.error(f"Error in get_event_progress_tool: {e}")
        return {"success": False, "error": str(e)}


def create_course_progress_sub_agent(opik_tracer, request_context: RequestContext) -> Agent:
    """Create the course progress sub-agent with request context"""

    def make_tool_with_context(tool_func):
        async def wrapped(user_message: str) -> Dict:
            return await tool_func(user_message, request_context)
        wrapped.__name__ = tool_func.__name__
        return wrapped

    tools = [
        make_tool_with_context(resolve_progress_target_tool),
        make_tool_with_context(get_course_progress_tool),
        make_tool_with_context(get_event_progress_tool),
    ]

    # Agent instruction: guide the workflow
    instruction = get_prompt("course_progress", "instruction")

    agent = Agent(
        name="course_progress_sub_agent",
        model="gemini-2.0-flash-001",
        description="Handles course progress and event completion diagnostics",
        instruction=instruction,
        tools=tools,
        before_agent_callback=opik_tracer.before_agent_callback,
        after_agent_callback=opik_tracer.after_agent_callback,
        before_model_callback=opik_tracer.before_model_callback,
        after_model_callback=opik_tracer.after_model_callback,
        before_tool_callback=opik_tracer.before_tool_callback,
        after_tool_callback=opik_tracer.after_tool_callback,
    )

    return agent
