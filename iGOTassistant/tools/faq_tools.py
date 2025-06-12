"""
This module contains the tools for the Karmayogi Bharat chatbot.
"""
import sys
import os
import datetime
from urllib import response
import uuid
import logging

from pathlib import Path
from docx import Document
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

from qdrant_client import QdrantClient
from qdrant_client.http import models

logger = logging.getLogger(__name__)


def initialize_environment():
    """
    Initialize the environment by loading the .env file and setting up global variables.
    This function should be called at the start of the application.
    """
    # Load environment variables from .env file
    load_dotenv()

    # Check required environment variables
    required_vars = ['KB_AUTH_TOKEN', 'KB_DIR']
    missing_vars = [var for var in required_vars if os.getenv(var) is None]

    if missing_vars:
        raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

    logging.info("Environment variables loaded successfully.")


def initialize_qdrant():
    """Initialize Qdrant vector database client"""
    try:
        client = QdrantClient(
            url=os.getenv("QDRANT_URL", "localhost"),
            port=int(os.getenv("QDRANT_PORT", "6333"))
        )

        collections = client.get_collections()

        if "KB_DOCS" in [c.name for c in collections.collections]:
            client.delete_collection("KB_DOCS")

        client.create_collection(
            collection_name="KB_DOCS",
            vectors_config=models.VectorParams(
                size=384,
                distance=models.Distance.COSINE
            ),
            # wait=True
        )
        return client
    except Exception as e:
        raise ValueError(f'Failed to initialize Qdrant: {e}')

def generate_point_id(doc_path: Path):
    return str(uuid.uuid4())


def process_documents(doc_path: Path):
    try:
        content = None
        ext = doc_path.suffix.lower()

        if ext in ['.txt', '.md']:
            with open(doc_path, 'r', encoding='utf-8') as f:
                content = f.read()
        elif ext == '.docx':
            doc = Document(doc_path)
            content = '\n'.join([para.text for para in doc.paragraphs])
        else:
            print(f'Unsupport file types: {ext}')
            return None, None
        
        if not content or not content.strip():
            print(f'Empty content in file: {doc_path}')
            return None, None

        metadata = {
            "source" : str(doc_path),
            "filename" : doc_path.name,
            "file_type" : ext,
            "last_modified" : datetime.datetime.fromtimestamp(doc_path.stat().st_mtime)
        }

        return content, metadata
    except Exception as e:
        print(f'Error processing the documents {doc_path}: {e}')
        return None, None

def initialize_knowledge_base():
    """
    Initialize the knowledge base by loading documents from the specified directory.
    This function should be called at the start of the application.
    """
    # Load documents from the specified directory
    kb_dir = os.getenv("KB_DIR")
    kb_path = Path(kb_dir)

    if not kb_path.exists() and not kb_path.is_dir():
        raise ValueError(f"Knowledge base directory does not exist: {kb_path}")

    documents = list(kb_path.glob('**/*.*'))

    if not documents:
        raise ValueError(f"No documents found in the knowledge base directory: {kb_path}")

    client = initialize_qdrant()
    model = initialize_embedding_model()

    points = []
    processed = 0

    for doc in documents:
        print(f'Processing:\t\t\t {doc.name}')
        content, metadata = process_documents(doc)
        if not content:
            continue

        try:
            embedding = model.encode(content)
            point_id = generate_point_id(doc)

            point = models.PointStruct(
                id=point_id,
                vector=embedding.tolist(),
                payload={
                    "content": content,
                    **metadata,
                }
            )
            points.append(point)
            processed += 1

            if len(points) >= 100:
                operation_info = client.upsert(
                    collection_name="KB_DOCS",
                    points=points
                )
                print(f'Batch upload status : {operation_info}')
                points = []
                print(f'Processed {processed} documents.')

        except Exception as e:
            print(f'Error processing {doc} : {e}')
            continue

    if points:
        operation_info = client.upsert(
            collection_name="KB_DOCS",
            points=points
        )
        print(f'Completed processing {processed} documents: Status {operation_info}')

    print('-'*100)
    collection_info = client.get_collection("KB_DOCS")
    print(collection_info)
    print('-' * 100)

    return kb_dir


def initialize_embedding_model():
    """
    Initialize the embedding model by loading the specified model.
    """
    try:
        model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        return model
    except (ImportError, ValueError, RuntimeError) as e:
        raise ValueError(f"Failed to initialize embedding model: {e}") from e



def answer_general_questions(userquestion: str):
    """
    This tool help answer the general questions user might have,
    this help can answer the question based knowledge base provided.

    Args:
        userquestion: This argument is question user has asked. This argument can't be empty.
    """
    try:
        model = initialize_embedding_model()
        question_embedding = model.encode(userquestion)
        
        client = QdrantClient(url=os.getenv("QDRANT_URL","localhost"), port=os.getenv("QDRANT_PORT","6333"))
        search_result = client.search(
            collection_name="KB_DOCS",
            query_vector=question_embedding.tolist(),
            limit=1
        )

        if search_result:
            return search_result[0].payload["content"]
        return "Couldn't file a relevant answer to your question."
        # global queryengine
        # response = queryengine.query(userquestion)
        # return str(response)
    except (AttributeError, TypeError, ValueError) as e:
        # logging.info('Unable to answer the question due to a specific error:', str(e))
        print('Error ', str(e))
        return "Unable to answer right now, please try again later."

    # return str(response)




try:
    initialize_environment()
    KB_AUTH_TOKEN = os.getenv('KB_AUTH_TOKEN')
    # search_client = initialize_search()
    KB_DIR = initialize_knowledge_base()
    response = answer_general_questions("What is karma points?")
    print(response)
    # initialize_embedding_model()

    # Load documents using the load_documents function
    # queryengine = load_documents(KB_DIR)

    # checking sample query
    # resp = queryengine.query("What is Karmayogi Bharat?")
    # logger.info('sample response %s', resp)
    logging.info("Knowledge base initialized successfully.")
    # return queryengine
except (ValueError, FileNotFoundError, ImportError, RuntimeError) as e:
    logging.info(f"Error initializing knowledge base: {e}")
    sys.exit(1)

logging.info("✅ Successfully initialized tools and knowledge base")

