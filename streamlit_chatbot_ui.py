#!/usr/bin/env python3
"""
Karmayogi KB Support Agent - Interactive Streamlit UI
====================================================
Interactive web interface to test the Karmayogi chatbot service.
"""

import streamlit as st
import requests
import json
import uuid
import time
from datetime import datetime
from typing import Dict, Any, Optional
import base64

# Custom CSS for user/bot message differentiation and sidebar status
st.markdown("""
<style>
.user-query {
    font-weight: bold;
    color: #111;
    background: #e3f2fd;
    padding: 0.5rem 1rem;
    border-radius: 0.4rem;
    margin-bottom: 0.5rem;
}
.service-status {
    background: #e8f5e8;
    color: #222;
    padding: 0.5rem 1rem;
    border-radius: 0.4rem;
    margin-bottom: 1rem;
    font-weight: 500;
}
</style>
""", unsafe_allow_html=True)

import streamlit as st
import requests
import json
import uuid
import time
from datetime import datetime
from typing import Dict, Any, Optional
import base64

# Page configuration
st.set_page_config(
    page_title="Karmayogi KB Support Agent",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better UI
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        color: #1f4e79;
        text-align: center;
        margin-bottom: 2rem;
    }
    .chat-message {
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 0.5rem 0;
    }
    .user-message {
        background-color: #e3f2fd;
        border-left: 4px solid #2196f3;
        color: #222;
    }
    .bot-message {
        background-color: #f1f8e9;
        border-left: 4px solid #4caf50;
        color: #222;
    }
    .error-message {
        background-color: #ffebee;
        border-left: 4px solid #f44336;
        color: #c62828;
    }
    .info-box {
        background-color: #fff3e0;
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 4px solid #ff9800;
    }
    .success-box {
        background-color: #e8f5e8;
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 4px solid #4caf50;
    }
    .feedback-section {
        background-color: #f5f5f5;
        padding: 0.5rem;
        border-radius: 0.3rem;
        margin-top: 0.5rem;
    }
    .stButton>button {
        padding: 0.25rem 0.75rem;
        font-size: 1.2rem;
    }
</style>
""", unsafe_allow_html=True)

class KarmayogiChatbotUI:
    def __init__(self):
        self.base_url = "http://localhost:8000"
        
    def check_service_health(self) -> bool:
        """Check if the chatbot service is running"""
        try:
            response = requests.get(f"{self.base_url}/health", timeout=5)
            return response.status_code == 200
        except Exception:
            return False
    
    def send_message(self, payload, headers, endpoint):
        try:
            response = requests.post(endpoint, json=payload, headers=headers, timeout=60)
            if response.status_code == 200:
                return {"success": True, "data": response.json()}
            else:
                return {"success": False, "error": f"HTTP {response.status_code}: {response.text}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

def main():
    # TTS Output selection
    tts_output = st.sidebar.selectbox(
        "TTS Output (audio in response)",
        [False, True],
        format_func=lambda x: "Yes" if x else "No",
        help="If True, backend will return audio (base64) in response."
    )
    """Main Streamlit application"""
    
    # Initialize the chatbot UI
    chatbot = KarmayogiChatbotUI()
    
    # Header
    st.markdown('<h1 class="main-header">🤖 Karmayogi KB Support Agent</h1>', unsafe_allow_html=True)
    
    # Sidebar configuration
    st.sidebar.title("⚙️ Configuration")
    
    # Service health check
    if chatbot.check_service_health():
        st.sidebar.markdown('<div class="service-status">✅ Service is running</div>', unsafe_allow_html=True)
    else:
        st.sidebar.markdown('<div class="error-message">❌ Service is not running<br/>Start the service with: <code>python main.py</code></div>', unsafe_allow_html=True)
        st.stop()
    
    # Chat mode selection
    chat_mode = st.sidebar.selectbox(
        "Chat Mode",
        ["Anonymous User", "Authenticated User"],
        help="Select whether to test as anonymous or authenticated user"
    )
    


    # User and Session configuration (always from sidebar)
    user_id = st.sidebar.text_input(
        "User ID",
        value=st.session_state.get("user_id", "placeholder"),
        help="Enter the user-id (as used in curl/Swagger)",
        placeholder="placeholder"
    )
    st.session_state.user_id = user_id

    # Channel selection
    channel = st.sidebar.selectbox(
        "Channel",
        ["web", "mobile"],
        help="Select the channel (web or mobile)"
    )

    # Language selection (add Malayalam)
    language = st.sidebar.selectbox(
        "Language",
        ["en", "hi", "ml"],
        help="Select language for the conversation"
    )

    # Authentication settings (only for authenticated mode)
    auth_cookie = ""
    if chat_mode == "Authenticated User":
        auth_cookie = st.sidebar.text_input(
            "Authentication Cookie",
            value="placeholder",
            help="Enter authentication cookie for authenticated requests"
        )


    # Display current user info
    st.sidebar.text(f"User ID: {user_id[:8]}...")

    # Reset session button
    if st.sidebar.button("🔄 Reset Session"):
        st.session_state.user_id = ""
        if "messages" in st.session_state:
            del st.session_state.messages
        st.rerun()
    
    # Initialize chat history
    if "messages" not in st.session_state:
        st.session_state.messages = []
    
    # Quick test buttons
    st.sidebar.markdown("### 🚀 Quick Tests")
    
    col1, col2 = st.sidebar.columns(2)
    
    with col1:
        if st.button("📚 Course Help", help="Test course enrollment query"):
            test_message = "How do I enroll in a course? I am new to the platform."
            st.session_state.test_message = test_message
    
    with col2:
        if st.button("🎓 Certificate", help="Test certificate issue"):
            test_message = "I cannot download my certificate. Please help."
            st.session_state.test_message = test_message
    
    col3, col4 = st.sidebar.columns(2)
    
    with col3:
        if st.button("🔐 OTP Issue", help="Test OTP login problem"):
            test_message = "What to do when i have OTP issues while logging in using Mobile number"
            st.session_state.test_message = test_message
    
    with col4:
        if st.button("👤 Profile", help="Test profile query"):
            test_message = "I need help with my profile verification"
            st.session_state.test_message = test_message
    
    # Hindi test button
    if st.sidebar.button("🌍 Hindi Test", help="Test Hindi language support"):
        test_message = "मुझे अपने कोर्स के बारे में जानकारी चाहिए"
        st.session_state.test_message = test_message
    
    # Main chat interface
    st.markdown("### 💬 Chat Interface")
    
    # Display chat history
    for idx, message in enumerate(st.session_state.messages):
        if message["role"] == "user":
            st.markdown(f'<div class="user-query">{message["content"]}</div>', unsafe_allow_html=True)
        else:
            # Show response time if present
            response_time_str = f"<span style='color: #888; font-size: 0.9em;'>(Response time: {message['response_time']:.2f} sec)</span>" if message.get("response_time") is not None else ""
            st.markdown(f"{message['content']} {response_time_str}", unsafe_allow_html=True)
            # If audio is present in the message, render audio player
            if message.get("audio"):
                st.markdown("**🔊 Audio Response:**")
                st.audio(base64.b64decode(message["audio"]), format="audio/wav")
            
            # Add feedback UI for bot messages (if trace_id OR thread_id exists and feedback not given)
            trace_id = message.get("trace_id")
            thread_id = message.get("thread_id") or message.get("session_id")
            if (trace_id or thread_id) and not message.get("feedback_given"):
                col1, col2, col3, col4 = st.columns([1, 1, 1, 8])
                
                with col1:
                    if st.button("👍", key=f"thumbs_up_{idx}"):
                        st.session_state[f"feedback_type_{idx}"] = "thumbs_up"
                        st.session_state[f"show_comment_{idx}"] = True
                
                with col2:
                    if st.button("👎", key=f"thumbs_down_{idx}"):
                        st.session_state[f"feedback_type_{idx}"] = "thumbs_down"
                        st.session_state[f"show_comment_{idx}"] = True
                
                with col3:
                    if st.button("💬", key=f"comment_{idx}", help="Add comment"):
                        st.session_state[f"show_comment_{idx}"] = True
                
                # Show comment box if user clicked any feedback button
                if st.session_state.get(f"show_comment_{idx}"):
                    comment = st.text_input(
                        "Optional comment (max 1000 chars):",
                        key=f"comment_text_{idx}",
                        max_chars=1000,
                        placeholder="Tell us more about your feedback..."
                    )
                    
                    col_submit, col_skip = st.columns([1, 1])
                    with col_submit:
                        feedback_type = st.session_state.get(f"feedback_type_{idx}")
                        button_label = f"Submit {'👍' if feedback_type == 'thumbs_up' else '👎' if feedback_type else '💬'}"
                        
                        if st.button(button_label, key=f"submit_feedback_{idx}"):
                            # Submit feedback to backend (use trace_id if available, otherwise thread_id)
                            feedback_payload = {
                                "feedback_type": feedback_type or "thumbs_up",
                                "comment": comment if comment else None
                            }
                            # Add trace_id if available (preferred)
                            if trace_id:
                                feedback_payload["trace_id"] = trace_id
                            # Always include thread_id for session grouping in Opik
                            thread_id_val = message.get("thread_id") or message.get("session_id")
                            if thread_id_val:
                                feedback_payload["thread_id"] = thread_id_val
                            
                            try:
                                response = requests.post(
                                    f"{chatbot.base_url}/feedback",
                                    json=feedback_payload,
                                    timeout=10
                                )
                                
                                if response.status_code == 200:
                                    result = response.json()
                                    message["feedback_given"] = True
                                    message["feedback_type"] = feedback_type or "thumbs_up"
                                    message["feedback_comment"] = comment
                                    
                                    # Clean up session state
                                    for key in [f"feedback_type_{idx}", f"show_comment_{idx}", f"comment_text_{idx}"]:
                                        if key in st.session_state:
                                            del st.session_state[key]
                                    
                                    st.success("✅ Thank you for your feedback!")
                                    st.rerun()
                                else:
                                    st.error(f"❌ Failed to submit feedback: {response.text}")
                            except Exception as e:
                                st.error(f"❌ Error submitting feedback: {str(e)}")
                    
                    with col_skip:
                        if st.button("Skip feedback", key=f"skip_feedback_{idx}"):
                            # Clean up and close comment box
                            for key in [f"feedback_type_{idx}", f"show_comment_{idx}", f"comment_text_{idx}"]:
                                if key in st.session_state:
                                    del st.session_state[key]
                            st.rerun()
            
            # Show feedback already given
            elif message.get("feedback_given"):
                feedback_emoji = "👍" if message.get("feedback_type") == "thumbs_up" else "👎"
                feedback_text = f"**Feedback:** {feedback_emoji}"
                if message.get("feedback_comment"):
                    feedback_text += f" - {message['feedback_comment']}"
                st.markdown(f"<span style='color: #888; font-size: 0.9em;'>✓ {feedback_text}</span>", unsafe_allow_html=True)
    
    # Input mode
    input_mode = st.radio("Input Mode", ["Text", "Audio"], horizontal=True)
    text_input = ""
    audio_bytes = None

    if input_mode == "Text":
        message_input = st.text_area(
            "Your message:",
            value=st.session_state.get("test_message", ""),
            height=100,
            placeholder="Type your message here... (e.g., 'How do I enroll in a course?')"
        )
    else:
        duration = st.slider("Recording duration (seconds)", 1, 20, 10)
        if st.button("Record Audio"):
            import sounddevice as sd
            import soundfile as sf
            import io
            st.info("Recording...")
            fs = 16000
            audio = sd.rec(int(duration * fs), samplerate=fs, channels=1, dtype='int16')
            sd.wait()
            buf = io.BytesIO()
            sf.write(buf, audio, fs, format='WAV')
            audio_bytes = buf.getvalue()
            st.audio(audio_bytes, format="audio/wav")
            st.success("Recording complete!")
            # Workaround: always convert to base64 string for API
            st.session_state["audio_b64"] = base64.b64encode(audio_bytes).decode("utf-8")
        message_input = ""

    # Clear the test message after displaying
    if "test_message" in st.session_state:
        del st.session_state.test_message

    col1, col2, col3 = st.columns([1, 1, 1])

    with col1:
        send_button = st.button("📤 Send Message", type="primary")

    with col2:
        if st.button("🗑️ Clear Chat"):
            st.session_state.messages = []
            st.rerun()

    with col3:
        if st.button("📋 Export Chat"):
            if st.session_state.messages:
                chat_export = {
                    "timestamp": datetime.now().isoformat(),
                    "user_id": st.session_state.user_id,
                    "mode": chat_mode,
                    "channel": channel,
                    "language": language,
                    "messages": st.session_state.messages
                }
                st.download_button(
                    "💾 Download Chat",
                    data=json.dumps(chat_export, indent=2),
                    file_name=f"chat_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                    mime="application/json"
                )

    # Send message logic
    if send_button and (message_input.strip() or (input_mode == "Audio" and st.session_state.get("audio_b64"))):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        user_message = {
            "role": "user",
            "content": message_input if input_mode == "Text" else "[Audio]",
            "timestamp": timestamp,
            "mode": chat_mode,
            "channel": channel,
            "language": language
        }
        st.session_state.messages.append(user_message)

        with st.spinner("🤔 Thinking..."):
            start_time = time.time()
            payload = {
                "channel_id": channel,
                "language": language
            }
            headers = {
                "Content-Type": "application/json",
                "user-id": user_id,
                "channel": channel
            }
            if chat_mode == "Authenticated User":
                headers["cookie"] = auth_cookie
            if input_mode == "Text" and message_input.strip():
                payload["text"] = message_input.strip()
            elif input_mode == "Audio":
                audio_b64 = st.session_state.get("audio_b64")
                if not audio_b64:
                    st.warning("No audio recorded. Please record audio before sending.")
                    return
                payload["audio"] = audio_b64
                payload["text"] = ""
            payload["tts_output"] = tts_output
            endpoint = f"{chatbot.base_url}/chat/send" if chat_mode == "Authenticated User" else f"{chatbot.base_url}/anonymous/chat/send"
            result = chatbot.send_message(payload, headers, endpoint)
            response_time = time.time() - start_time
        if result["success"]:
            # Debug: Show full backend response
            with st.expander("🔍 Raw Backend Response", expanded=False):
                st.json(result["data"])
            # Prefer 'text' key, fallback to 'response', then fallback message
            bot_response = result["data"].get("text")
            if not bot_response:
                bot_response = result["data"].get("response", "No response received")
            # Store audio in chat history if present
            audio_b64 = result["data"].get("audio")
            # Capture trace_id and thread_id (session_id) for feedback
            trace_id = result["data"].get("trace_id")
            thread_id = result["data"].get("thread_id")  # Backend now returns thread_id
            session_id = result["data"].get("session_id") or thread_id  # Fallback to thread_id
            timestamp_value = result["data"].get("timestamp")
            
            bot_message = {
                "role": "assistant",
                "content": bot_response,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "response_time": response_time,
                "trace_id": trace_id,  # Store trace_id for feedback
                "thread_id": thread_id,  # Store thread_id (session_id) for conversation tracking
                "session_id": session_id,  # Keep for compatibility
                "backend_timestamp": timestamp_value,
                "feedback_given": False  # Track if feedback was provided
            }
            if tts_output and audio_b64:
                bot_message["audio"] = audio_b64
            st.session_state.messages.append(bot_message)
            st.success(f"✅ Response received in {response_time:.2f} sec")
        else:
            error_message = {
                "role": "assistant",
                "content": f"❌ Error: {result['error']}",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "response_time": response_time
            }
            st.session_state.messages.append(error_message)
            st.error(f"❌ Error occurred: {result['error']}")
        # Clear audio_b64 after sending
        if "audio_b64" in st.session_state:
            del st.session_state["audio_b64"]
        st.rerun()
    
    # Sample queries section
    with st.expander("💡 Sample Queries"):
        st.markdown("""
        **Course Related:**
        - How do I enroll in a course?
        - I cannot see my enrolled courses
        - How to complete a course?
        
        **Certificate Issues:**
        - I cannot download my certificate
        - My certificate is not showing
        - Certificate verification process
        
        **Login Problems:**
        - What to do when i have OTP issues while logging in using Mobile number
        - I forgot my password
        - Account verification issues
        
        **Profile Management:**
        - How to update my profile?
        - My friend's profile is not verified. How can i verify it
        - Change email or mobile number
        
        **Hindi Queries:**
        - मुझे अपने कोर्स के बारे में जानकारी चाहिए
        - मैं अपना प्रोफाइल कैसे अपडेट करूं?
        - सर्टिफिकेट डाउनलोड कैसे करें?
        """)
    
    # API Information
    with st.expander("🔧 API Information"):
        st.markdown(f"""
        **Service URL:** `{chatbot.base_url}`
        
        **Endpoints:**
        - Anonymous Chat: `POST /anonymous/chat/send`
        - Authenticated Chat: `POST /chat/send`
        - Feedback Collection: `POST /feedback`
        - Health Check: `GET /health`
        
        **Current Session:**
        - User ID: `{st.session_state.user_id}`
        - Mode: `{chat_mode}`
        - Channel: `{channel}`
        - Language: `{language}`
        
        **Feedback Feature:**
        - Each bot response includes a unique trace_id
        - Click 👍 for positive feedback or 👎 for negative feedback
        - Optionally add a comment to explain your feedback
        - Feedback is stored in Opik for analytics
        """)

if __name__ == "__main__":
    main()