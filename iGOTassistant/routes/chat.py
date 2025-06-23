"""
Chat routes for the Karmayogi Bharat chatbot API.
"""
import os
from typing import Annotated
import redis
import requests

from fastapi import APIRouter, HTTPException,Header
from dotenv import load_dotenv

from ..models.chat import Request
from ..agent_fastapi import ChatAgent
from ..config.config import API_ENDPOINTS

load_dotenv()

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
    payload = {}
    headers = {
    'accept': 'application/json, text/plain, */*',
    'Cookie': cookies,
    }
    print("auth_user:: url:: ", url)
    response = requests.request("GET", url, headers=headers, data=payload, timeout=60)

    print(response.text)
    if response.status_code == 200 and response.json()['params']['status'] == 'SUCCESS':
        return True
    
    return False



@router.post("/start")
async def start_chat(user_id: Annotated[str | None, Header()] = None, cookie: Annotated[str | None, Header()] = None, request : Request = None):
    """Endpoint to start a new chat session."""
    try:
        # if valid:
        #    return await agent.start_new_session(request)
        # else:
        #     return HTTPException(status_code=500, detail="Authentication failed")
        print({"User-Agent request headers:: ", user_id, cookie})
        # return True
        stored_cookies = redis_client.get(user_id)
        print(f"Reading cookie from redis for {user_id} :: {stored_cookies}" )
        request.session_id = str(cookie).replace("connect.sid=", "") if cookie else None
        print(f" {user_id} session_id:: {request.session_id}")
        if stored_cookies is None:
            print(f" {user_id} :: Invoking auth_user with cookie:: {cookie}")
            auth_cookies = auth_user(str(cookie))
            print(f"{user_id}:: Auth cookies: {auth_cookies}")
            if auth_cookies:
                print(f'{user_id}:: Storing the cookie in redis')
                await redis_client.set(user_id, str(cookie))
            else:
                raise HTTPException(status_code=403, detail="Authentication failure.")

        if cookie is None or str(cookie) != stored_cookies.decode('utf-8'):
            raise HTTPException(status_code=403, detail="Authentication failure.")

        return await agent.start_new_session(user_id, request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

@router.post("/send")
async def continue_chat(request: Request, user_id: Annotated[str | None, Header()] = None, cookie: Annotated[str | None, Header()] = None):
    """Endpoint to continue an existing chat session."""
    try:
        print({"User-Agent request headers:: ", user_id, cookie})
        # return True
        stored_cookies = redis_client.get(user_id)
        print(f"Reading cookie from redis for {user_id} :: {stored_cookies}" )

        request.session_id = str(cookie).replace("connect.sid=","") if cookie else None
        print(f" {user_id} session_id:: {request.session_id}")
        if stored_cookies is None:
            print(f" {user_id} :: Invoking auth_user with cookie:: {cookie}")
            auth_cookies = auth_user(str(cookie))
            print(f"{user_id}:: Auth cookies: {auth_cookies}")
            if auth_cookies:
                print(f'{user_id}:: Storing the cookie in redis')
                await redis_client.set(user_id, str(cookie))
            else:
                raise HTTPException(status_code=403, detail="Authentication failure.")

        if cookie is None or str(cookie) != stored_cookies.decode('utf-8'):
            raise HTTPException(status_code=403, detail="Authentication failure.")

        return await agent.send_message(user_id, request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
