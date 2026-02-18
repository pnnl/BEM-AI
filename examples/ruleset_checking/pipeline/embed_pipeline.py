import argparse
import json
import os
import sys
import uuid

import chromadb
from langchain_ollama import OllamaEmbeddings


def embed_texts(texts, embedder):
    """Embed a list of strings using LangChain Ollama embeddings."""
    return embedder.embed_documents(texts)


def main():
    parser = argparse.ArgumentParser(description="Import RCT dataset ChromaDB (Ollama embeddings)")
    parser.add_argument("--json_path", default="./train_data.jsonl", help="Path to JSON file")
    parser.add_argument("--collection", default="rct_rules", help="Chroma collection name")
    parser.add_argument("--persist-dir", default="./chroma_persist", help="Chroma persistent directory")
    parser.add_argument("--embed-model", default="mxbai-embed-large",
                        help="Ollama embedding model name")
    args = parser.parse_args()

    # --- Load JSON ---
    with open(args.json_path, "r") as f:
        json_list = list(f)

    data = []
    for json_str in json_list:
        result = json.loads(json_str)
        data.append(result)

    if not isinstance(data, list):
        print("ERROR: JSON must contain a list of items.")
        sys.exit(1)

    entries = []
    metadatas = []
    for item in data:
        if isinstance(item, dict) and "rule_description" in item:
            description = str(item["rule_description"])
            entries.append(description)
            metadatas.append(item)

    cleaned_metadatas = [
        {k: v for k, v in m.items() if v is not None}
        for m in metadatas
    ]

    # clean up meta data

    if not entries:
        print("No valid entries found.")
        sys.exit(0)

    # --- Initialize Ollama Embeddings ---
    embedder = OllamaEmbeddings(model=args.embed_model)

    # --- Initialize ChromaDB persistent client (1.2.2) ---
    client = chromadb.PersistentClient(path=args.persist_dir)

    # --- Get or create collection ---
    if args.collection in [c.name for c in client.list_collections()]:
        collection = client.get_collection(args.collection)
    else:
        collection = client.create_collection(args.collection)

    # --- Embed all questions ---
    try:
        embeddings = embed_texts(entries, embedder)
    except Exception as e:
        print("Embedding error:", e)
        sys.exit(1)

    # --- Prepare insert data ---
    ids = [str(uuid.uuid4()) for _ in entries]
    # --- Insert into collection ---
    collection.add(
        ids=ids,
        documents=entries,
        metadatas=cleaned_metadatas,
        embeddings=embeddings
    )

    print(f"Successfully imported {len(entries)} entries into ChromaDB (collection='{args.collection}').")
    print(f"Persistent directory: {args.persist_dir}")


if __name__ == "__main__":
    main()



