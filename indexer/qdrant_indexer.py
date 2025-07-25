# index_to_qdrant.py

import json
import os
import argparse

from tqdm import tqdm
from qdrant_client import QdrantClient
from qdrant_client.http import models
from sentence_transformers import SentenceTransformer


def main():
    # Load model
    model = SentenceTransformer("all-MiniLM-L6-v2")
    collection_name = os.getenv("QDRANT_COLLECTION_NAME", "kb_bot_knowledge_base")
    qdrant_host = os.getenv("QDRANT_HOST", "localhost")
    qdrant_port = int(os.getenv("QDRANT_PORT", 6333))

    # Initialize Qdrant client (use your actual host & API key if needed)
    client = QdrantClient(qdrant_host, port=qdrant_port)

    # Create collection if it doesn't exist
    if not client.get_collection(collection_name):
        print(f"Creating collection '{collection_name}'...")
        if client.get_collection(collection_name) is not None:
            print(f"Collection '{collection_name}' already exists. Skipping creation.")
        else:
            print(f"Collection '{collection_name}' does not exist. Creating it now...")
            client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(size=384, distance=models.Distance.COSINE)
            )


    # Read input file
    parser = argparse.ArgumentParser(description="Index data to Qdrant")
    parser.add_argument("input_file", help="Path to the input JSONL file")
    args = parser.parse_args()
    input_file = args.input_file

    with open(input_file, "r", encoding="utf-8") as f:
        items = [json.loads(line) for line in f]

    payloads = []
    vectors = []
    ids = []

    print("Generating embeddings and preparing payloads...")
    for idx, item in enumerate(tqdm(items)):
        embedding = model.encode(item["text"])
        payload = {
            "topic": item["topic"],
            "text": item["text"]
        }
        payloads.append(payload)
        vectors.append(embedding)
        ids.append(idx)

    print("Uploading to Qdrant...")
    client.upsert(
        collection_name=collection_name,
        points=models.Batch(
            ids=ids,
            vectors=vectors,
            payloads=payloads
        )
    )
    print("Indexing complete! ✅")


if __name__ == "__main__":
    main()
