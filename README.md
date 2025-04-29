# iGOT Assistant

A conversational AI assistant for the iGOT (Integrated Government Online Training) platform using Google's Gemini model.

## Features

- 🔒 User authentication via email
- 📚 Course enrollment status and details
- ❓ Smart Q&A using document knowledge base
- 💬 Persistent chat session management
- 🚀 RESTful API endpoints
- 🔍 Certificate verification support

## Prerequisites

- Python 3.8 or higher
- Google Cloud credentials (gemini_api.json) or API_KEY.
- Access to iGOT platform APIs
- Docker ( optional )

## Installation 

1. Clone the repository:
```bash
# Clone the repository
git clone https://github.com/KB-iGOT/kb-support-agent-service.git
cd kb-support-agent-service
```

2. Set up environment:
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
```

3. Install dependencies
```bash
# Install uv
pip install uv

# Install dependencies using uv
uv install -r requirements.txt
```

4. Configure credentials:
- Place your `gemini_api.json` in the project root
- Set up environment variables (if needed) in .env file
```bash
GOOGLE_APPLICATION_CREDENTIALS=""  # gemini_api.json file path 
KB_DIR=""       # directory path of knowledge base.
KB_AUTH_TOKEN=""       # auth token for iGOT api
GEMINI_MODEL="gemini-2.0-flash-exp" # gemini model name
KB_BASE_URL=""    # base url for Karmayogi bharat platform
BHASHINI_USER_ID="your bhashini user id"
BHASHINI_API_KEY="bhashini api key"
BHASHINI_PIPELINE_ID="bhashini pipeline id"

GCP_BUCKET_NAME="your gcp bucket name"
GCP_STORAGE_CREDENTIALS="google credential files for storage"
```
### Environment Setup

Create a `gemini_api.json` file with your Google Cloud credentials in the project root.

## Usage

### FastAPI Backend

```bash
# Start the FastAPI server
uvicorn agent:app --reload
```

#### Using Docker

Before building the Dockerfile make sure you setup .env and gemini_api.json as well as docs for knowledge base.

```bash
docker build -t igot-assistant .
docker run -p 8000:8000 -v ./docs:/app/docs igot-assistant
```

The API will be available at `http://localhost:8000`

## API Endpoints

- `POST /chat/start`: Initialize a new chat session
- `POST /chat/send`: Send messages in an existing chat session

## API Usage

### Start a Chat Session
```bash
curl -X POST http://localhost:8000/chat/start \
     -H "Content-Type: application/json" \
     -d '{"sessionid": "user123", "text": "Hello"}'
```

```sessionid``` is unique to the session and must be handled by the chat interface application. Its necessary to start the chat session first before every conversational session.

### Send a Message
```bash
curl -X POST http://localhost:8000/chat/send \
     -H "Content-Type: application/json" \
     -d '{"sessionid": "user123", "text": "How do I verify my certificate?"}'
```

Provide unique ```sessionid``` that you started your session with.

## Project Structure

```
├── fronend
│   ├── README.md
│   └── streamlit_chat.py
├── src
│   ├── config/
│   ├── libs/
│   ├── models/
│   ├── routes/
│   ├── tools/
│   ├── utils/
│   ├── __init__.py
│   ├── main.py
│   ├── prompt.py
│   └── agent.py
├── LICENSE
├── pyproject.toml
├── README.md
├── requirements.txt
├── setup.py
├── Dockerfile
└── uv.lock
```
## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit changes
4. Push to the branch
5. Open a Pull Request

## License

MIT License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

- Technical issues: Open an issue on GitHub