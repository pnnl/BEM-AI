
import argparse
import os

from chromadb import PersistentClient
from langchain_community.embeddings import OllamaEmbeddings


def main():
    parser = argparse.ArgumentParser(description="Query ChromaDB using Ollama embeddings")
    parser.add_argument("query", help="Search query text")
    parser.add_argument("--collection", default="helpdesk_qna", help="Collection name")
    parser.add_argument("--persist-dir", default="./chroma_persist", help="Chroma persistent directory")
    parser.add_argument("--embed-model", default="mxbai-embed-large", help="Ollama embedding model name")
    parser.add_argument("--k", type=int, default=5, help="Number of results to return")
    args = parser.parse_args()

    # --- Initialize embedding model ---
    embedder = OllamaEmbeddings(model=args.embed_model)

    # Embed the query
    query_embedding = embedder.embed_query(args.query)

    # --- Connect to ChromaDB ---
    client = PersistentClient(path=args.persist_dir)

    # Ensure collection exists
    try:
        collection = client.get_collection(args.collection)
    except Exception:
        print(f"Collection '{args.collection}' not found.")
        return

    # --- Perform similarity search ---
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=args.k,
        include=["documents", "metadatas", "distances"]
    )

    # --- Display results ---
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    dists = results.get("distances", [[]])[0]

    print("\n=== Search Results ===\n")
    for i, (doc, meta, dist) in enumerate(zip(docs, metas, dists), start=1):
        print(f"Result {i}:")
        print(f"Question: {doc}")
        print(f"Answer:   {meta.get('answer')}")
        print(f"Distance: {dist:.4f}")
        print("-" * 50)

    print("\Done.")


if __name__ == "__main__":
    main()