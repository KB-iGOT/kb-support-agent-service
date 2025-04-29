# Karmayogi Bharat Chatbot UI

A Streamlit-based chat interface for the iGOT Assistant that connects to a FastAPI backend.

## Features

- 💬 Real-time chat interface
- 🔄 Persistent session management
- 🚀 Integration with FastAPI backend
- 📝 Markdown support for messages
- ⚡ Async message handling

## Prerequisites

- Python 3.8+
- FastAPI backend running on port 8000
- Streamlit

## Installation

1. Clone the repository and navigate to the frontend directory:
```bash
cd fronend
```

2. Install the required packages:
```bash
pip install streamlit requests
```

## Usage

1. Make sure the FastAPI backend is running:
```bash
cd ..  # Navigate to root directory
uvicorn main:app --reload --port 8000
```

2. Start the Streamlit application:
```bash
cd frontend
streamlit run streamlit_chat.py
```

3. Open your browser and visit:
```
http://localhost:8501
```

## Configuration

The application uses these default settings:
- Backend URL: `http://127.0.0.1:8000`
- API Endpoints:
  - Start Chat: `/chat/start/`
  - Send Message: `/chat/send/`
- Request Timeout: 60 seconds

To modify these settings, update the URLs in `streamlit_chat.py`.

## Features

- **Session Management**: Automatically generates and maintains unique session IDs
- **Chat History**: Preserves conversation history during the session
- **Error Handling**: Graceful handling of backend connection issues
- **Markdown Support**: Renders formatted text in chat messages
- **Real-time Updates**: Instant message display and response

## Project Structure

```
frontend/
├── streamlit_chat.py  # Main Streamlit application
└── README.md         # This documentation
```

## Contributing

1. Fork the repository
2. Create your feature branch
3. Commit your changes
4. Push to the branch
5. Create a new Pull Request

## License

MIT License - see the [LICENSE](LICENSE) file for details.

## Support

For issues and feature requests, please create an issue in the repository.