"""
This is a simple Streamlit app that interacts with a FastAPI backend to create a chatbot interface.

NOTE: This code assumes that the FastAPI backend is running locally on port 8000 
and has endpoints for starting a chat session and sending messages.
"""
import uuid
import streamlit as st
import requests

st.title("Karmayogi Bharat Chatbot")

if "sessionid" not in st.session_state:
    # Generate a new session ID if it doesn't exist
    st.session_state.sessionid = str(uuid.uuid4())

if "messages" not in st.session_state:
    st.session_state.messages = []

# Start chat session
if "chat_started" not in st.session_state:
    try:
        response = requests.post(
            "http://127.0.0.1:8000/chat/start/",
            json={"sessionid": st.session_state.sessionid, "text": ""},
            timeout=60
        )
        if response.status_code == 200:
            st.session_state.chat_started = True
            st.session_state.messages = []  # Initialize messages after starting chat
        else:
            st.error("Failed to start chat session.")
    except requests.exceptions.RequestException as e:
        st.error(f"Error connecting to FastAPI: {e}")

if "chat_started" in st.session_state and st.session_state.chat_started:
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if prompt := st.chat_input("What is up?"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        try:
            response = requests.post(
                "http://127.0.0.1:8000/chat/send/",
                json={"text": prompt, "sessionid": st.session_state.sessionid},
                timeout=60
            )
            msg = response.json()["response"]

            st.session_state.messages.append({"role": "assistant", "content": msg})
            with st.chat_message("assistant"):
                st.markdown(msg)
        except requests.exceptions.RequestException as e:
            st.error(f"Error connecting to FastAPI: {e}")
