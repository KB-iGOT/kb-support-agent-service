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

from fastapi import HTTPException
from fastembed import TextEmbedding

from numpy import isin
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

    logger.info("Environment variables loaded successfully.")


def initialize_qdrant():
    """Initialize Qdrant vector database client"""
    try:
        client = QdrantClient(
            url=os.getenv("QDRANT_URL", "localhost"),
            port=int(os.getenv("QDRANT_PORT", "6333")),
            check_compatibility=False
        )

        collections = client.get_collections()
        if client.collection_exists("KB_DOCS"):
            logger.info("Embedding already exists, returning.")
            return client

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

def generate_point_id(doc_path: Path, chunk_index: int = None):
    if chunk_index is not None:
        # Create a UUID based on the document path and chunk index for consistency
        import hashlib
        doc_hash = hashlib.md5(str(doc_path).encode()).hexdigest()
        chunk_hash = hashlib.md5(f"{doc_hash}_{chunk_index}".encode()).hexdigest()
        # Convert to UUID format
        return f"{chunk_hash[:8]}-{chunk_hash[8:12]}-{chunk_hash[12:16]}-{chunk_hash[16:20]}-{chunk_hash[20:32]}"
    else:
        return str(uuid.uuid4())


def split_content_into_chunks(content: str, chunk_size: int = 1000, overlap: int = 200):
    """
    Split content into overlapping chunks for better semantic search.
    
    Args:
        content: The text content to split
        chunk_size: Maximum size of each chunk
        overlap: Number of characters to overlap between chunks
    
    Returns:
        List of text chunks
    """
    if len(content) <= chunk_size:
        return [content]
    
    chunks = []
    start = 0
    
    while start < len(content):
        end = start + chunk_size
        
        # If this is not the last chunk, try to break at a sentence boundary
        if end < len(content):
            # Look for sentence endings within the last 200 characters of the chunk
            # but ensure we don't create chunks smaller than chunk_size * 0.5
            min_chunk_size = int(chunk_size * 0.5)
            search_start = max(start + min_chunk_size, end - 200)
            
            for i in range(end, search_start, -1):
                if content[i-1] in '.!?\n':
                    end = i
                    break
        
        chunk = content[start:end].strip()
        if chunk and len(chunk) >= min_chunk_size:
            chunks.append(chunk)
        
        # Move start position for next chunk, accounting for overlap
        start = end - overlap
        if start >= len(content):
            break
    
    return chunks


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
        elif ext == '.json':
            import json
            with open(doc_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
                # Convert JSON to readable text format
                content = json.dumps(json_data, indent=2, ensure_ascii=False)
        elif ext == '.csv':
            import pandas as pd
            try:
                # Read CSV file
                df = pd.read_csv(doc_path, encoding='utf-8')
                # Convert DataFrame to readable text format
                content = df.to_string(index=False)
            except Exception as csv_error:
                logger.error(f'Error reading CSV file {doc_path}: {csv_error}')
                # Fallback: try reading as plain text
                with open(doc_path, 'r', encoding='utf-8') as f:
                    content = f.read()
        else:
            logger.warning(f'Unsupported file type: {ext} for file {doc_path.name}')
            return None, None
        
        if not content or not content.strip():
            logger.warning(f'Empty content in file: {doc_path}')
            return None, None
        
        # Log content length for debugging
        logger.info(f'Extracted {len(content)} characters from {doc_path.name}')

        # Split content into chunks
        chunks = split_content_into_chunks(content)
        logger.info(f'Split {doc_path.name} into {len(chunks)} chunks')
        
        # Log chunk sizes for debugging
        if chunks:
            chunk_sizes = [len(chunk) for chunk in chunks]
            logger.info(f'Chunk sizes for {doc_path.name}: min={min(chunk_sizes)}, max={max(chunk_sizes)}, avg={sum(chunk_sizes)//len(chunk_sizes)}')

        metadata = {
            "source" : str(doc_path),
            "filename" : doc_path.name,
            "file_type" : ext,
            "last_modified" : datetime.datetime.fromtimestamp(doc_path.stat().st_mtime)
        }

        return chunks, metadata
    except Exception as e:
        logger.error(f'Error processing the documents {doc_path}: {e}')
        return None, None

def initialize_knowledge_base(force_refresh=False):
    """
    Initialize the knowledge base by loading documents from the specified directory.
    This function should be called at the start of the application.
    
    Args:
        force_refresh: If True, will reprocess all documents even if collection exists
    """
    # Load documents from the specified directory
    kb_dir = os.getenv("KB_DIR")
    kb_path = Path(kb_dir)

    if not kb_path.exists() and not kb_path.is_dir():
        raise ValueError(f"Knowledge base directory does not exist: {kb_path}")

    documents = list(kb_path.glob('**/*.*'))
    logger.info(f"Found {len(documents)} documents in {kb_path}")
    
    # Log all found documents for debugging
    for doc in documents:
        logger.info(f"Found document: {doc.name} ({doc.suffix})")

    if not documents:
        raise ValueError(f"No documents found in the knowledge base directory: {kb_path}")

    client = initialize_qdrant()
    
    # Check if collection exists and has points
    if client.collection_exists("KB_DOCS") and not force_refresh:
        collection_info = client.get_collection("KB_DOCS")
        if collection_info.points_count > 0:
            logger.info(f"Collection already exists with {collection_info.points_count} points. Skipping processing.")
            return True
        else:
            logger.info("Collection exists but has no points. Reprocessing documents.")
    
    model = initialize_embedding_model()

    points = []
    processed = 0
    skipped = 0

    for doc in documents:
        logger.info(f'Processing:\t\t\t {doc.name}')
        chunks, metadata = process_documents(doc)
        if not chunks:
            logger.warning(f'No content extracted from {doc.name}, skipping...')
            skipped += 1
            continue

        try:
            for chunk_index, chunk in enumerate(chunks):
                embedding = list(model.embed(chunk))
                if not embedding:
                    logger.warning(f'No embedding generated for chunk {chunk_index} of {doc.name}, skipping...')
                    skipped += 1
                    continue

                point_id = generate_point_id(doc, chunk_index)

                point = models.PointStruct(
                    id=point_id,
                    vector=embedding[0].tolist(),
                    payload={
                        "content": chunk,
                        "chunk_index": chunk_index,
                        "total_chunks": len(chunks),
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
                    logger.info(f'Batch upload status : {operation_info}')
                    points = []
                    logger.info(f'Processed {processed} chunks so far.')

        except Exception as e:
            logger.error(f'Error processing {doc} : {e}')
            skipped += 1
            continue

    if points:
        operation_info = client.upsert(
            collection_name="KB_DOCS",
            points=points
        )
        logger.info(f'Final batch upload status: {operation_info}')
    
    logger.info(f'Completed processing {processed} chunks total')
    logger.info(f'Skipped {skipped} chunks due to errors or empty content')
    
    # Verify collection has points
    collection_info = client.get_collection("KB_DOCS")
    logger.info(f'Collection info: {collection_info.points_count} points in collection')

    return kb_dir


def initialize_embedding_model():
    """
    Initialize the embedding model by loading the specified model.
    """
    try:
        model = TextEmbedding()
        # model = TextEmbedding(
        #     model_name="BAAI/bge-small-en-v1.5",
        #     max_length=512,
        #     normalize_embeddings=True
        # )
        # model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        return model
    except (ImportError, ValueError, RuntimeError) as e:
        raise ValueError(f"Failed to initialize embedding model: {e}") from e


def clear_knowledge_base():
    """
    Clear the knowledge base collection. Use this to force a complete refresh.
    """
    try:
        client = QdrantClient(url=os.getenv("QDRANT_URL","localhost"), port=os.getenv("QDRANT_PORT","6333"))
        if client.collection_exists("KB_DOCS"):
            client.delete_collection("KB_DOCS")
            logger.info("Knowledge base collection cleared successfully.")
        else:
            logger.info("Knowledge base collection does not exist.")
        return True
    except Exception as e:
        logger.error(f"Error clearing knowledge base: {e}")
        return False



def answer_general_questions(userquestion: str):
    """
    This tool help answer the general questions user might have,
    this help can answer the question based knowledge base provided.

    Args:
        userquestion: This argument is question user has asked. This argument can't be empty.
    """
    if not userquestion or not isinstance(userquestion, str):
        raise HTTPException(status_code=400, detail="Question must be a non-empty string.")

    # Retry logic for connection issues
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Use the same initialization function to ensure consistent connection
            client = initialize_qdrant()
            
            # Check if collection exists and has points
            if not client.collection_exists("KB_DOCS"):
                return "Knowledge base is not initialized. Please initialize the knowledge base first."
            
            collection_info = client.get_collection("KB_DOCS")
            if collection_info.points_count == 0:
                return "Knowledge base is empty. Please add documents to the knowledge base."
            
            model = initialize_embedding_model()
            question_embedding = list(model.embed(userquestion))
            
            search_result = client.search(
                collection_name="KB_DOCS",
                query_vector=question_embedding[0].tolist(),
                limit=3
            )

            if search_result:
                return search_result[0].payload["content"]
            return "Couldn't find a relevant answer to your question."
            
        except (AttributeError, TypeError, ValueError, ConnectionError, Exception) as e:
            logger.error(f'Error in answer_general_questions (attempt {attempt + 1}): {str(e)}')
            if attempt == max_retries - 1:
                return "Unable to answer right now, please try again later."
            else:
                import time
                time.sleep(1)  # Wait 1 second before retry





