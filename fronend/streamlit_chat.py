"""
This is a simple Streamlit app that interacts with a FastAPI backend to create a chatbot interface.

NOTE: This code assumes that the FastAPI backend is running locally on port 8000 
and has endpoints for starting a chat session and sending messages.
"""
import uuid
import streamlit as st
import requests

st.title("Karmayogi Bharat Chatbot")

if "session_id" not in st.session_state:
    # Generate a new session ID if it doesn't exist
    st.session_state.session_id = str(uuid.uuid4())

if "user_id" not in st.session_state:
    st.session_state.user_id = "df1a1d6c-39f2-4847-b02c-8d8c04c7dcb3"  # Default test user

if "cookie" not in st.session_state:
    st.session_state.cookie = None

if "messages" not in st.session_state:
    st.session_state.messages = []

API_URL = "http://localhost:8000/chat"

def send_message(message: str):
    """Send message to chat API with proper headers"""

    headers = {
        "Content-Type" : "application/json",
        "user-id": st.session_state.user_id
    }

    if st.session_state.cookie:
        headers["cookie"] = st.session_state.cookie

    if not st.session_state.messages:
        endpoint = f"{API_URL}/start"
    else:
        endpoint = f"{API_URL}/send"

    try:
        if not headers.get("cookie"):
            st.warning("Cookie is empty! Please set a valid cookie in the sidebar.")

        print(headers)

        response = requests.post(
            endpoint,
            headers=headers,
            json={
                "channel_id": "web",
                "session_id": st.session_state.session_id,
                "text" : message,
                "language" : "en",
                "audio" : "",
            },
            timeout=60,
        )
        print(response.text)

        if "Set-Cookie" in response.headers:
            st.session_state.cookie = response.headers["Set-Cookie"]

        if response.status_code == 200:
            return response.json()["text"]
        else:
            return f"Error: {response.status_code} - {response.text}"
    except Exception as e:
        return f"Error: {str(e)}"
    
# st.session_state.cookies = ""

user_id = st.sidebar.text_input("User ID", value=st.session_state.user_id)
cookie = st.sidebar.text_input("Cookie", value=st.session_state.cookie )
if not cookie:
    st.sidebar.warning("Please enter a valid cookie. Cookie should not be empty.")
if cookie != st.session_state.cookie:
    # print(cookie)
    st.session_state.cookie = cookie

if user_id != st.session_state.user_id:
    st.session_state.user_id = user_id
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("What's up !"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        response = send_message(prompt)
        st.markdown(response)
        st.session_state.messages.append({"role": "assistant", "content": response})

if st.sidebar.button("Clear Chat"):
    st.session_state.messages = []
    st.rerun()


# Start chat session
# if "chat_started" not in st.session_state:
#     try:
#         response = requests.post(
#             "http://127.0.0.1:8000/chat/start/",
#             json={
#                 "channel_id": "web",
#                 "session_id": st.session_state.session_id,
#                 "text": "",
#                 "language": "en",
#                 "audio" : "",
#                 },
#             timeout=60
#         )
#         if response.status_code == 200:
#             st.session_state.chat_started = True
#             st.session_state.messages = []  # Initialize messages after starting chat
#         else:
#             st.error("Failed to start chat session.")
#     except requests.exceptions.RequestException as e:
#         st.error(f"Error connecting to FastAPI: {e}")

# if "chat_started" in st.session_state and st.session_state.chat_started:
#     for message in st.session_state.messages:
#         with st.chat_message(message["role"]):
#             st.markdown(message["content"])

#     if prompt := st.chat_input("What is up?"):
#         st.session_state.messages.append({"role": "user", "content": prompt})
#         with st.chat_message("user"):
#             st.markdown(prompt)

#         try:
#             response = requests.post(
#                 "http://127.0.0.1:8000/chat/send/",
#                 json={
#                     "channel_id":"web",
#                     "language":"en",
#                     "text": prompt,
#                     "session_id": st.session_state.session_id,
#                     "audio": "",
#                     },
#                 timeout=60
#             )
#             if response.status_code == 200:
#                 MSG = response.json()["text"]
#             else:
#                 st.error("Failed to get response from server.")
#                 MSG = "Sorry, I couldn't process your request at the moment."

#             st.session_state.messages.append({"role": "assistant", "content": MSG})
#             with st.chat_message("assistant"):
#                 st.markdown(MSG)
#         except requests.exceptions.RequestException as e:
#             st.error(f"Error connecting to FastAPI: {e}")
