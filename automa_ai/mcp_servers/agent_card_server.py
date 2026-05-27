### MCP Server to sourcing agent cards.
import json
import logging
import os
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions
from mcp.server import FastMCP


# BASE_DIR = Path(__file__).resolve().parent.parent  # goes from automa_ai/mcp_servers/ -> automa_ai/
# AGENT_CARDS_DIR = BASE_DIR / "agent_cards"
MODEL = "ollama_chat/llama3.1:8b"

logger = logging.getLogger(__name__)

MCP_NAME = "agent_card_mcp"

# ---- 1. Initialize ChromaDB client & embedding function ----
def get_chroma_client(persist_dir: str = "./chroma_store"):
    """Initialize a persistent ChromaDB client."""
    return chromadb.Client(chromadb.config.Settings(persist_directory=persist_dir))


def get_embedding_function():
    """Use Chroma's default embedding function (SentenceTransformers)."""
    return embedding_functions.DefaultEmbeddingFunction()
    # Or specify explicitly:
    # return embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")

# ---- 2. Load agent cards ----
def load_agent_cards(agent_card_dir: str):
    """Load JSON agent cards from a directory."""
    card_uris = []
    agent_cards = []
    dir_path = Path(agent_card_dir)

    if not dir_path.is_dir():
        logger.error(f"Agent cards directory not found or is not a directory: {agent_card_dir}")
        return [], []

    logger.info(f"Loading agent cards from card repo: {agent_card_dir}")

    for filename in os.listdir(agent_card_dir):
        if filename.lower().endswith(".json"):
            file_path = dir_path / filename
            if file_path.is_file():
                try:
                    with file_path.open("r", encoding="utf-8") as f:
                        data = json.load(f)
                        card_uris.append(f"resource://agent_cards/{Path(filename).stem}")
                        agent_cards.append(data)
                except Exception as e:
                    logger.error(f"Error loading {filename}: {e}", exc_info=True)

    logger.info(f"Finished loading agent cards. Found {len(agent_cards)} cards.")
    return card_uris, agent_cards

# ---- 3. Build embeddings and store in Chroma ----
def build_agent_card_embeddings(agent_card_dir: str, persist_dir: str = "./chroma_store"):
    """
    Load agent cards and populate the ChromaDB collection with their embeddings.
    Returns the collection object for reuse.
    """
    client = get_chroma_client(persist_dir)
    embed_fn = get_embedding_function()
    collection = client.get_or_create_collection(name="agent_cards", embedding_function=embed_fn)

    card_uris, agent_cards = load_agent_cards(agent_card_dir)
    if not agent_cards:
        logger.warning("No agent cards found to embed.")
        return collection

    # Focus text: concatenate only name and description
    documents = []
    metadatas = []

    for uri, card in zip(card_uris, agent_cards):
        name = card.get("name", "")
        description = card.get("description", "")
        embed_text = f"{name}\n{description}".strip()
        if not embed_text:
            embed_text = json.dumps(card)  # fallback if both missing
        documents.append(embed_text)  # <-- full card JSON stored here
        metadatas.append({"uri": uri, "full_card": json.dumps(card)})

    # Safely clear existing entries
    existing = collection.get(include=[])
    if existing["ids"]:
        collection.delete(ids=existing["ids"])

    # Add all documents
    collection.add(
        documents=documents,
        metadatas=metadatas,
        ids=card_uris,
    )

    logger.info(f"Indexed {len(agent_cards)} agent cards into ChromaDB.")
    return collection

def _keyword_agent_uri(query: str) -> str | None:
    normalized = query.lower()

    if any(term in normalized for term in ("run simulation", "annual simulation", "simulate")):
        return "resource://agent_cards/simulation_agent"

    if any(term in normalized for term in ("window-to-wall", "window to wall", "wwr", "envelope", "insulation")):
        return "resource://agent_cards/envelope_agent"

    if any(term in normalized for term in ("lighting", "lpd", "daylighting")):
        return "resource://agent_cards/lighting_agent"

    if (
        any(term in normalized for term in ("retrieve", "report", "record", "get"))
        and any(term in normalized for term in ("eui", "energy use intensity", "output", "result"))
    ):
        return "resource://agent_cards/output_agent"

    if any(term in normalized for term in ("generate", "load", "template", "typical", "baseline model")):
        return "resource://agent_cards/template_agent"

    return None


# ---- 4. Query the best match ----
def find_best_match(query: str, persist_dir: str = "./chroma_store") -> dict | None:
    """Find the most semantically similar agent card to a text query."""
    client = get_chroma_client(persist_dir)
    embed_fn = get_embedding_function()
    collection = client.get_or_create_collection(name="agent_cards", embedding_function=embed_fn)

    keyword_uri = _keyword_agent_uri(query)
    if keyword_uri:
        keyword_match = collection.get(ids=[keyword_uri])
        if keyword_match["metadatas"]:
            logger.info(f"Query text: {query}")
            logger.info(f"Keyword-routed match: {keyword_uri}")
            return {
                "uri": keyword_uri,
                "agent_card": json.loads(keyword_match["metadatas"][0]["full_card"]),
                "distance": 0.0,
            }

    results = collection.query(query_texts=[query], n_results=1)

    if not results["ids"] or not results["ids"][0]:
        logger.warning("No matching agent card found.")
        return None

    best_uri = results["ids"][0][0]
    best_doc = results["documents"][0][0]
    best_metadata = results["metadatas"][0][0]
    best_distance = results["distances"][0][0]

    logger.info(f"Query text: {query}")
    logger.info(f"Best match: {best_doc}")

    logger.info(f"Best match: {best_uri} (distance={best_distance:.4f})")
    return {
        "uri": best_uri,
        "agent_card": json.loads(best_metadata["full_card"]),
        "distance": best_distance
    }

# ---- 5. Get card by URI ----
def get_card_by_uri(uri: str, persist_dir: str = "./chroma_store") -> dict | None:
    """Retrieve an agent card by URI directly from ChromaDB."""
    client = get_chroma_client(persist_dir)
    embed_fn = get_embedding_function()
    collection = client.get_or_create_collection(name="agent_cards", embedding_function=embed_fn)

    results = collection.get(ids=[uri])
    if not results["documents"]:
        return None
    if not results["metadatas"]:
        return None
    return json.loads(results["metadatas"][0]["full_card"])


def serve(host, port, transport, agent_cards_dir: str):
    """Initialize and runs the agent cards mcp_servers server.
    Args:
        host: The hostname or IP address to bind the server to.
        port: The port number to bind the server to.
        transport: The transport mechanism for the MCP server (e.g., 'stdio', 'sse')
        agent_cards_dir: directory to agent_cards

    Raises:
        ValueError
    """
    logger.info("Starting Agent Cards MCP Server")
    mcp = FastMCP("agent-cards", host=host, port=port)

    build_agent_card_embeddings(agent_cards_dir)

    @mcp.tool(
        name="find_agent",
        description="Finds the most relevant agent card based on a natural language query string.",
    )
    def find_agent(query: str) -> dict:
        """
        Finds the most relevant agent card based on a query string.

        This function takes a user query, typically a natural language question or a task generated by an agent,
        generates its embedding, and compares it against the
        pre-computed embedding of the loaded agent cards. It uses the dot product to measure similarity and identifies the agent card with the highest similarity score.

        Args:
            query: The natual language query string used to search for a relevant agent.

        Returns:
            The json representing the agent card deemed most relevant to the input query based on embedding similarity.
        """
        return find_best_match(query)["agent_card"]

    @mcp.resource("resource://agent_cards/{card_name}", mime_type="application/json")
    def get_agent_card(card_name: str) -> dict:
        """Retrieves an agent card as a json / dictionary for the MCP resource endpoint.

        This function serves as the handler for the MCP resource identified by
            the URI 'resource://agent_cards/{card_name}'.

        Returns:
            A json / dictionary
        """
        uri = f"resource://agent_cards/{card_name}"
        card = get_card_by_uri(uri)
        if card:
            return {"agent_card": card}
        return {}

    logger.info(f"Agent cards MCP Server at {host}:{port} and transport {transport}")
    mcp.run(transport=transport)
