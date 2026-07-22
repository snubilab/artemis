import logging
from typing import Optional

import chromadb
from chromadb.config import Settings as ChromaSettings
from src.settings import settings

logger = logging.getLogger(__name__)

# Singleton MedCPT embedding function (lazy)
_medcpt_ef = None


def get_chroma_client():
    """
    Returns a ChromaDB client.
    Uses HTTP client when CHROMA_URL is set, otherwise local persistent storage.
    """
    if settings.CHROMA_URL:
        from urllib.parse import urlparse
        parsed = urlparse(settings.CHROMA_URL)
        host = parsed.hostname or "localhost"
        port = parsed.port or 8000
        client = chromadb.HttpClient(host=host, port=port)
        return client

    client = chromadb.PersistentClient(
        path=settings.CHROMA_PERSIST_DIRECTORY
    )
    return client


def _get_medcpt_embedding_function():
    """Get or create a singleton MedCPT embedding function."""
    global _medcpt_ef
    if _medcpt_ef is None:
        from src.utils.medcpt_embedding import MedCPTEmbeddingFunction
        _medcpt_ef = MedCPTEmbeddingFunction(
            device=settings.MEDCPT_DEVICE,
            batch_size=64,
        )
        logger.info(f"MedCPT embedding function initialized (device={settings.MEDCPT_DEVICE})")
    return _medcpt_ef


def get_collection(name: str, embedding_model: Optional[str] = None):
    """
    Get or create a collection with optional embedding model selection.
    
    Args:
        name: Base collection name (e.g. "omop_concepts")
        embedding_model: Override embedding model. If None, uses settings.EMBEDDING_MODEL.
            Options: "default" (ChromaDB built-in), "medcpt" (MedCPT bi-encoder)
    
    Returns:
        ChromaDB Collection with appropriate embedding function
    """
    client = get_chroma_client()
    model = embedding_model or settings.EMBEDDING_MODEL
    
    if model == "medcpt":
        # MedCPT: use separate collection with custom embedding function
        collection_name = f"{name}_medcpt"
        ef = _get_medcpt_embedding_function()
        return client.get_or_create_collection(
            name=collection_name,
            embedding_function=ef,
        )
    else:
        # Default: ChromaDB built-in (all-MiniLM-L6-v2)
        return client.get_or_create_collection(name=name)
