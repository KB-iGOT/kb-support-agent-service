# index_to_qdrant.py

import json
from tqdm import tqdm
from qdrant_client import QdrantClient
from qdrant_client.http import models
from sentence_transformers import SentenceTransformer


def main():
    # Load model
    model = SentenceTransformer("all-MiniLM-L6-v2")

    # Initialize Qdrant client (use your actual host & API key if needed)
    client = QdrantClient("localhost", port=6333)

    # Create collection if doesn't exist
    collection_name = "igot_docs"
    client.recreate_collection(
        collection_name=collection_name,
        vectors_config=models.VectorParams(size=384, distance=models.Distance.COSINE)
    )

    # Read input file
    input_file = "/home/jayaprakashnarayanaswamy/KB/kb-support-agent-service/indexer/input.jsonl"
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
