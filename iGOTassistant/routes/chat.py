"""
Chat routes for the Karmayogi Bharat chatbot API.
"""
import hashlib
import json
import os
import re
from typing import Annotated
import redis
import requests
import logging

from fastapi import APIRouter, HTTPException,Header
from dotenv import load_dotenv

from ..models.chat import Request
from ..agent_fastapi import ChatAgent
from ..config.config import API_ENDPOINTS

load_dotenv()
logger = logging.getLogger(__name__)

redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST"),
    port=os.getenv("REDIS_PORT"),
    db=os.getenv("REDIS_DB")
    )

router = APIRouter(prefix="/chat", tags=["chat"])
agent = ChatAgent()

@router.get("/")
async def health_check():
    """Health check endpoint to verify chat service status."""
    return {"message": "Chat service is running"}

def auth_user(cookies):
    """cookie verification"""
    url = API_ENDPOINTS["PROXIES"]
    print(cookies, '*'*100)
    payload = {}
    headers = {
    'accept': 'application/json, text/plain, */*',
    # 'accept': 'application/json',
    'Cookie': cookies,
    }
    print("auth_user:: url:: ", url)
    response = requests.request("GET", url, headers=headers, data=payload, timeout=60)

    print("auth_user:: response:: ", response.text)
    if response.status_code == 200: # and response.json()['params']['status'] == 'SUCCESS':
        try:
            if response.text.strip() == "":
                return False

            data = response.json()
            if data["params"]["status"] == 'SUCCESS':
                return True
        except json.JSONDecodeError as e:
            logger.info(f"JSON decode error in auth_user: {e}")
            return False
    
    return False



@router.post("/start")
async def start_chat(
                    user_id: Annotated[str | None, Header()] = None,
                    cookie: Annotated[str | None, Header()] = None,
                    request : Request = None):
    """Endpoint to start a new chat session."""
    try:
        
        print({"User-Agent request headers:: ", user_id, cookie})
        stored_cookies = redis_client.get(user_id)
        print(f"Reading cookie from redis for {user_id} :: {stored_cookies}" )
        if request.channel_id == "web":
            if cookie is None:
                return { "message": "Missing Cookie."}
            match = re.search(r'connect\.sid=([^;]+)', str(cookie)) if cookie else None
            # request.session_id = match.group(1) if match else None
            request.session_id = hashlib.sha256(match.group(1).encode("utf-8")).hexdigest()
            if request.session_id is None:
                return { "message" : "Not able to create the session."}
        print(f" {user_id} session_id:: {request.session_id}")
        if stored_cookies is None or str(cookie) != stored_cookies.decode('utf-8'):
            print(f" {user_id} :: Invoking auth_user with cookie:: {cookie}")
            auth_cookies = auth_user(str(cookie))
            print(f"{user_id}:: Auth cookies: {auth_cookies}")
            if auth_cookies:
                print(f'{user_id}:: Storing the cookie in redis')
                redis_client.set(user_id, str(cookie))
            else:
                raise HTTPException(status_code=403, detail="Authentication failure.")

        return await agent.start_new_session(user_id, request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

@router.post("/send")
async def continue_chat(
                request: Request,
                user_id: Annotated[str | None, Header()] = None,
                cookie: Annotated[str | None, Header()] = None):
    """Endpoint to continue an existing chat session."""
    try:
        print({"User-Agent request headers:: ", user_id, cookie})
        if request.channel_id == "web" :
            stored_cookies = redis_client.get(user_id)
            print(f"Reading cookie from redis for {user_id} :: {stored_cookies}" )

            if cookie is None:
                return { "message": "Missing Cookie."}

            match = re.search(r'connect\.sid=([^;]+)', str(cookie)) if cookie else None
            # request.session_id = match.group(1) if match else None
            request.session_id = hashlib.sha256(match.group(1).encode("utf-8")).hexdigest()
            if request.session_id is None:
                return { "message" : "Not able to create the session."}
            print(f" {user_id} session_id:: {request.session_id}")

            if stored_cookies is None or str(cookie) != stored_cookies.decode('utf-8'):
                print(f" {user_id} :: Invoking auth_user with cookie:: {cookie}")
                auth_cookies = auth_user(str(cookie))
                print(f"{user_id}:: Auth cookies: {auth_cookies}")

                if auth_cookies:
                    print(f'{user_id}:: Storing the cookie in redis')
                    redis_client.set(user_id, str(cookie))
                else:
                    raise HTTPException(status_code=403, detail="Authentication failure.")

        return await agent.send_message(user_id, request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
