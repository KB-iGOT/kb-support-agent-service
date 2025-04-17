# iGOT Assistant

A conversational AI assistant for the iGOT (Integrated Government Online Training) platform using Google's Gemini model and LangChain.

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
pip install -r requirements.txt
```

4. Configure credentials:
- Place your `gemini_api.json` in the project root
- Set up environment variables (if needed) in .env file
```bash
GEMINI_CRED=""  # gemini_api.json file path 
KB_DIR=""       # directory path of knowledge base.
BEARER=""       # auth token for iGOT api
GEMINI_MODEL="gemini-2.0-flash-exp" # gemini model name
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
```bash
docker build -t igot-assistant .
docker run -p 8000:8000 igot-assistant
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

### Send a Message
```bash
curl -X POST http://localhost:8000/chat/send \
     -H "Content-Type: application/json" \
     -d '{"sessionid": "user123", "text": "How do I verify my certificate?"}'
```

## Project Structure

```
kb-support-agent-service/
├── docs/            # Knowledge base documents
├── frontend/            # streamlit frontend
├── tools/            # All support tools for the agent
├── utils/            # utility tools
├── requirements.txt  # Project dependencies
├── agent.py           # FastAPI backend server
├── setup.py         # Package configuration
├── prompt.py         # Package configuration
├── Dockerfile       # Container configuration
└── README.md        # Project documentation
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