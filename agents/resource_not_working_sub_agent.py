import logging
import os
from typing import Dict, List, Optional

from google.adk.agents import Agent
from opik import track

from utils.request_context import RequestContext
from utils.course_module_status_api import get_module_status_api_client
from utils.prompt_loader import get_prompt

logger = logging.getLogger(__name__)

OPIK_PROJECT = os.getenv("OPIK_PROJECT", "default")


def _normalize(s: str) -> str:
    return " ".join((s or "").lower().split())


@track(name="resolve_course_by_name_tool", project_name=OPIK_PROJECT)
async def resolve_course_by_name_tool(user_message: str, request_context: RequestContext = None) -> Dict:
    """
    Resolve a course from the user's enrollments by fuzzy name match. Returns list of matches if ambiguous.
    Response: { success, matches: [{name, id, batch_id}] }
    """
    try:
        if not request_context:
            return {"success": False, "error": "Missing context"}

        query = user_message.strip()
        matches: List[Dict] = []
        for c in request_context.get_course_enrollments():
            name = c.get("course_name") or c.get("content", {}).get("name")
            cid = c.get("course_identifier") or c.get("courseId") or c.get("contentId")
            batch = c.get("course_batch_id") or c.get("batchId")
            if name and cid and (_normalize(query) in _normalize(name) or _normalize(name) in _normalize(query)):
                matches.append({"name": name, "id": cid, "batch_id": batch})

        if not matches:
            # Provide all courses as catalog for user to pick
            catalog = []
            for c in request_context.get_course_enrollments():
                name = c.get("course_name") or c.get("content", {}).get("name")
                cid = c.get("course_identifier") or c.get("courseId") or c.get("contentId")
                batch = c.get("course_batch_id") or c.get("batchId")
                if name and cid:
                    catalog.append({"name": name, "id": cid, "batch_id": batch})
            return {"success": True, "matches": catalog, "note": "no_direct_match"}

        return {"success": True, "matches": matches}
    except Exception as e:
        logger.error(f"resolve_course_by_name_tool error: {e}")
        return {"success": False, "error": str(e)}


@track(name="get_inprogress_modules_tool", project_name=OPIK_PROJECT)
async def get_inprogress_modules_tool(user_message: str, request_context: RequestContext = None) -> Dict:
    """
    Given a message containing a course do_id or after resolving a single course, fetch in-progress module IDs.
    Response: { success, course_id, course_name, in_progress_ids: [do_id], module_map: {id: {name, object_type}} }
    """
    try:
        if not request_context:
            return {"success": False, "error": "Missing context"}

        # Try extract course id
        course_id: Optional[str] = None
        tokens = user_message.replace("\n", " ").split()
        for t in tokens:
            if t.startswith("do_"):
                course_id = t
                break

        if not course_id:
            # Attempt resolution from a prior step's user_message (assume it is the course name)
            resolved = await resolve_course_by_name_tool(user_message, request_context)
            if not resolved.get("success"):
                return resolved
            matches = resolved.get("matches", [])
            if len(matches) == 1:
                course_id = matches[0]["id"]
            else:
                return {
                    "success": True,
                    "action": "disambiguate_course",
                    "options": [{"name": m["name"], "id": m["id"]} for m in matches]
                }

        api = await get_module_status_api_client()
        details = await api.get_detailed_module_status(request_context.user_id, course_id)
        if not details:
            return {"success": False, "error": "Unable to fetch course details"}

        inprog = details.get("module_breakdown", {}).get("in_progress", {}).get("modules", [])
        in_progress_ids = [m.get("id") for m in inprog if m.get("id")]

        # Fetch names for in-progress ids
        name_map = await (await get_module_status_api_client()).fetch_module_names(in_progress_ids)

        return {
            "success": True,
            "course_id": course_id,
            "course_name": details.get("course_name"),
            "in_progress_ids": in_progress_ids,
            "module_map": name_map,
        }
    except Exception as e:
        logger.error(f"get_inprogress_modules_tool error: {e}")
        return {"success": False, "error": str(e)}


@track(name="find_resource_in_modules_tool", project_name=OPIK_PROJECT)
async def find_resource_in_modules_tool(user_message: str, request_context: RequestContext = None) -> Dict:
    """
    Given a resource name and (optionally) a context that includes prior in-progress list, try to find a matching module.
    Expects message format: "<resource name> | in:<comma-separated-doids>" (optional in: list).
    Returns: { success, found: bool, resource: {id, name, type} }
    """
    try:
        if not request_context:
            return {"success": False, "error": "Missing context"}

        msg = user_message.strip()
        parts = [p.strip() for p in msg.split("|")]
        resource_query = parts[0]
        in_ids: List[str] = []
        name_map: Dict[str, Dict] = {}

        # Try parse provided in-progress ids
        for p in parts[1:]:
            if p.startswith("in:"):
                raw = p.split(":", 1)[1].strip()
                in_ids = [x.strip() for x in raw.split(",") if x.strip()]

        api = await get_module_status_api_client()
        if in_ids:
            name_map = await api.fetch_module_names(in_ids)
        else:
            # As a fallback, try to use all leaf nodes of a resolved course if present in message
            course_id = None
            for t in msg.split():
                if t.startswith("do_"):
                    course_id = t
                    break
            if course_id:
                # fetch structure and names
                structure = await api.fetch_course_structure(course_id)
                ids = structure.get("leaf_nodes", [])
                name_map = await api.fetch_module_names(ids)

        # Fuzzy match by name
        target = None
        rq = _normalize(resource_query)
        for mid, meta in name_map.items():
            nm = meta.get("name", "")
            if nm and (rq in _normalize(nm) or _normalize(nm) in rq):
                target = {"id": mid, "name": nm, "type": meta.get("object_type", "Content")}
                break

        if not target:
            return {"success": True, "found": False}

        return {"success": True, "found": True, "resource": target}
    except Exception as e:
        logger.error(f"find_resource_in_modules_tool error: {e}")
        return {"success": False, "error": str(e)}


def create_resource_not_working_sub_agent(opik_tracer, request_context: RequestContext) -> Agent:
    """Create sub-agent handling 'Resource is not working' flow without overlapping others"""

    def with_ctx(tool):
        async def wrapped(user_message: str) -> Dict:
            return await tool(user_message, request_context)
        wrapped.__name__ = tool.__name__
        return wrapped

    tools = [
        with_ctx(resolve_course_by_name_tool),
        with_ctx(get_inprogress_modules_tool),
        with_ctx(find_resource_in_modules_tool),
    ]

     instruction = get_prompt("resource_not_working", "instruction")

    agent = Agent(
        name="resource_not_working_sub_agent",
        model="gemini-2.0-flash-001",
        description="Diagnoses unplayable resource issues and guides to ticket if unresolved",
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
