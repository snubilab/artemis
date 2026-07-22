"""
MedCPT Embedding Function for ChromaDB.

Wraps the asymmetric MedCPT bi-encoder (Query Encoder + Article Encoder)
into ChromaDB's EmbeddingFunction interface.

MedCPT: Contrastive Pre-trained Transformers for zero-shot biomedical IR.
  - Paper: https://doi.org/10.1038/s42256-023-00742-x
  - Query Encoder: ncbi/MedCPT-Query-Encoder
  - Article Encoder: ncbi/MedCPT-Article-Encoder
"""
import logging
from typing import List, cast

import numpy as np
from chromadb.api.types import (
    Documents,
    EmbeddingFunction,
    Embeddings,
)

logger = logging.getLogger(__name__)

# Model identifiers on HuggingFace
MEDCPT_QUERY_MODEL = "ncbi/MedCPT-Query-Encoder"
MEDCPT_ARTICLE_MODEL = "ncbi/MedCPT-Article-Encoder"


def _lazy_import_torch():
    """Import torch lazily to avoid import errors when not installed."""
    try:
        import torch
        return torch
    except ImportError:
        raise ImportError(
            "PyTorch is required for MedCPT embeddings. "
            "Install with: pip install torch"
        )


def _lazy_import_transformers():
    """Import transformers lazily to avoid import errors when not installed."""
    try:
        from transformers import AutoModel, AutoTokenizer
        return AutoModel, AutoTokenizer
    except ImportError:
        raise ImportError(
            "HuggingFace Transformers is required for MedCPT embeddings. "
            "Install with: pip install transformers"
        )


class MedCPTArticleEmbeddingFunction(EmbeddingFunction[Documents]):
    """
    MedCPT Article (Document) Encoder.
    
    Used for INDEXING documents into ChromaDB.
    Encodes concept names / document text using the Article Encoder.
    """

    def __init__(self, device: str = "cpu", batch_size: int = 64):
        self.device = device
        self.batch_size = batch_size
        self._model = None
        self._tokenizer = None

    def _load_model(self):
        if self._model is not None:
            return
        
        torch = _lazy_import_torch()
        AutoModel, AutoTokenizer = _lazy_import_transformers()
        
        logger.info(f"Loading MedCPT Article Encoder on {self.device}...")
        self._tokenizer = AutoTokenizer.from_pretrained(MEDCPT_ARTICLE_MODEL)
        self._model = AutoModel.from_pretrained(MEDCPT_ARTICLE_MODEL).to(self.device)
        self._model.eval()
        logger.info("✅ MedCPT Article Encoder loaded")

    def __call__(self, input: Documents) -> Embeddings:
        self._load_model()
        torch = _lazy_import_torch()
        
        all_embeddings: List[List[float]] = []
        
        for i in range(0, len(input), self.batch_size):
            batch = input[i : i + self.batch_size]
            
            # Article encoder expects [[title, abstract]] pairs
            # For OMOP concepts, we use concept_name as both
            encoded = self._tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="pt",
            ).to(self.device)
            
            with torch.no_grad():
                outputs = self._model(**encoded)
                # Use [CLS] token embedding
                embeds = outputs.last_hidden_state[:, 0, :]
                embeds = embeds.cpu().numpy()
            
            for emb in embeds:
                all_embeddings.append(emb.tolist())
        
        return cast(Embeddings, all_embeddings)


class MedCPTQueryEmbeddingFunction(EmbeddingFunction[Documents]):
    """
    MedCPT Query Encoder.
    
    Used for SEARCHING — encodes user queries at retrieval time.
    """

    def __init__(self, device: str = "cpu"):
        self.device = device
        self._model = None
        self._tokenizer = None

    def _load_model(self):
        if self._model is not None:
            return
        
        torch = _lazy_import_torch()
        AutoModel, AutoTokenizer = _lazy_import_transformers()
        
        logger.info(f"Loading MedCPT Query Encoder on {self.device}...")
        self._tokenizer = AutoTokenizer.from_pretrained(MEDCPT_QUERY_MODEL)
        self._model = AutoModel.from_pretrained(MEDCPT_QUERY_MODEL).to(self.device)
        self._model.eval()
        logger.info("✅ MedCPT Query Encoder loaded")

    def __call__(self, input: Documents) -> Embeddings:
        self._load_model()
        torch = _lazy_import_torch()
        
        encoded = self._tokenizer(
            input,
            padding=True,
            truncation=True,
            max_length=256,
            return_tensors="pt",
        ).to(self.device)
        
        with torch.no_grad():
            outputs = self._model(**encoded)
            embeds = outputs.last_hidden_state[:, 0, :]
            embeds = embeds.cpu().numpy()
        
        return cast(Embeddings, [emb.tolist() for emb in embeds])


class MedCPTEmbeddingFunction(EmbeddingFunction[Documents]):
    """
    Unified MedCPT embedding function for ChromaDB.
    
    Delegates to the Article Encoder (indexing) by default.
    For query-time search, ChromaDB calls collection.query(query_texts=...)
    which internally calls this function — we route to Query Encoder.
    
    IMPORTANT: ChromaDB only supports a SINGLE embedding function per collection.
    Since collection.add() and collection.query() both call the same function,
    we use a mode flag to switch between encoders.
    
    Usage:
        # For indexing (add documents)
        ef = MedCPTEmbeddingFunction(device="cpu")
        ef.set_mode("index")
        collection.add(documents=[...])
        
        # For querying (search)
        ef.set_mode("query")
        collection.query(query_texts=[...])
    """

    def __init__(self, device: str = "cpu", batch_size: int = 64):
        self.device = device
        self.batch_size = batch_size
        self._article_ef = MedCPTArticleEmbeddingFunction(
            device=device, batch_size=batch_size
        )
        self._query_ef = MedCPTQueryEmbeddingFunction(device=device)
        # Default mode: query (most common at runtime after indexing)
        self._mode = "query"

    def set_mode(self, mode: str):
        """Switch between 'index' (Article Encoder) and 'query' (Query Encoder)."""
        assert mode in ("index", "query"), f"Invalid mode: {mode}"
        self._mode = mode
        logger.debug(f"MedCPT mode set to: {mode}")

    def __call__(self, input: Documents) -> Embeddings:
        if self._mode == "index":
            return self._article_ef(input)
        else:
            return self._query_ef(input)
