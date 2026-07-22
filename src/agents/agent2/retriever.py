import os
from typing import List, Dict, Any, Optional
from src.utils.vector import get_collection
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

class CandidateConcept(BaseModel):
    concept_id: int
    concept_name: str
    domain_id: str
    vocabulary_id: str
    concept_class_id: str
    distance: float  # Vector distance (lower is better)
    adjusted_score: float = 0.0  # After preference scoring (lower is better)

# Vocabulary preferences per domain (lower bonus = higher priority)
_VOCAB_PREFERENCE: Dict[str, Dict[str, float]] = {
    "Condition": {"SNOMED": -0.10, "ICD10CM": 0.05},
    "Drug":      {"RxNorm": -0.15, "RxNorm Extension": -0.05, "ATC": 0.10},
    "Measurement": {"LOINC": -0.30, "SNOMED": 0.20},
    "Procedure": {"SNOMED": -0.15, "CPT4": -0.05, "HCPCS": 0.0},
    "Observation": {"SNOMED": -0.05, "LOINC": -0.03},
    "Device":    {"SNOMED": -0.05, "HCPCS": -0.03},
}

# concept_class_ids that are less clinically useful — penalize
_PENALIZED_CLASSES = {
    "Clinical Finding",  # SNOMED "findings" that are often too generic
    "Observable Entity", # SNOMED observables — not standard for measurements
    "Qualifier Value",
    "Context-dependent",
    "Attribute",
    "Record Artifact",
    "Staging / Scales",
    "Undefined",
}

# Preferred concept_class_ids per domain
_PREFERRED_CLASSES: Dict[str, set] = {
    "Condition": {"Disorder", "Clinical Finding"},
    "Drug": {"Ingredient", "Clinical Drug Comp", "Clinical Drug"},
    "Measurement": {"Clinical Observation", "Lab Test"},
    "Procedure": {"Procedure", "4-dig billing code", "CPT4"},
}

import json
import os

# ... (omitted previous code)

# Common/Reliable concepts derived from external config (Data-Driven)
# Loaded dynamically in __init__

class ConceptRetriever:
    def __init__(self, collection_name: str = "omop_concepts"):
        self.collection = get_collection(collection_name)
        self.concept_weights = self._load_concept_weights()
        
    def _load_concept_weights(self) -> Dict[int, float]:
        """Load concept priorities from defaults and DB stats."""
        weights = {}
        
        # 1. Load Defaults (Manual high-priority list for bootstrapping)
        try:
            default_path = os.path.join(os.path.dirname(__file__), "resources/concept_priority_defaults.json")
            if os.path.exists(default_path):
                with open(default_path) as f:
                    defaults = json.load(f)
                    for k, v in defaults.items():
                        weights[int(k)] = float(v)
            else:
                logger.warning(f"Default concept weights not found at {default_path}")
        except Exception as e:
            logger.error(f"Failed to load default weights: {e}")

        # 2. Load DB Stats (Auto-generated from Synthea/MIMIC)
        try:
            db_path = os.path.join(os.path.dirname(__file__), "resources/concept_priority_db.json")
            if os.path.exists(db_path):
                with open(db_path) as f:
                    db_stats = json.load(f)
                    for k, v in db_stats.items():
                        cid = int(k)
                        val = float(v)
                        # Prefer the stronger boost (minimum value)
                        if cid in weights:
                            weights[cid] = min(weights[cid], val)
                        else:
                            weights[cid] = val
                logger.info(f"Loaded {len(db_stats)} concept weights from DB stats")
            else:
                logger.info("No DB concept stats found (concept_priority_db.json). Run scripts/generate_concept_stats.py to generate.")
        except Exception as e:
            logger.error(f"Failed to load DB weights: {e}")
            
        logger.info(f"Final Concept Weights loaded: {len(weights)} concepts")
        return weights
    
    def search(
        self, 
        query_text: str, 
        n_results: int = 20,
        domain_hint: Optional[str] = None,
    ) -> List[CandidateConcept]:
        """
        Searches the vector database with post-retrieval scoring:
        1. Vector semantic search (ChromaDB)
        2. Vocabulary preference scoring by domain
        3. Exact substring match boosting
        4. Re-sort by adjusted_score
        """
        # Fetch more candidates for better post-filtering
        fetch_n = max(n_results * 3, 60)
        
        try:
            results = self.collection.query(
                query_texts=[query_text],
                n_results=fetch_n,
                include=["metadatas", "distances", "documents"]
            )
        except Exception as e:
            print(f"Vector search failed (DB might be empty): {e}")
            return []

        candidates = []
        if results and results['ids']:
            ids = results['ids'][0]
            metadatas = results['metadatas'][0]
            distances = results['distances'][0]
            documents = results.get('documents', [[]])[0]

            query_lower = query_text.lower().strip()

            for i, cid in enumerate(ids):
                meta = metadatas[i]
                concept_name = (
                    documents[i] if i < len(documents) 
                    else meta.get("concept_name", "Unknown")
                )
                domain = meta.get("domain_id", "Unknown")
                vocab = meta.get("vocabulary_id", "Unknown")
                concept_class = meta.get("concept_class_id", "Unknown")
                dist = distances[i]

                # --- Adjusted score = base distance + modifiers ---
                score = dist

                # 1. Vocabulary preference bonus
                effective_domain = domain_hint or domain
                vocab_prefs = _VOCAB_PREFERENCE.get(effective_domain, {})
                score += vocab_prefs.get(vocab, 0.05)  # default: small penalty

                # 2. Exact / substring match boost
                name_lower = concept_name.lower()
                if name_lower == query_lower:
                    score -= 0.15  # strong boost for exact match
                elif query_lower in name_lower:
                    score -= 0.08  # boost for substring
                elif name_lower in query_lower:
                    score -= 0.04  # partial boost
                else:
                    # Word-level prefix match (catches hypertension/hypertensive)
                    query_words = set(query_lower.split())
                    name_words = set(name_lower.split())
                    # Check if any query word shares a 6+ char prefix with name word
                    for qw in query_words:
                        if len(qw) < 5:
                            continue
                        prefix = qw[:min(len(qw)-2, 8)]  # e.g. "hypertens" from "hypertension"
                        for nw in name_words:
                            if nw.startswith(prefix):
                                score -= 0.06  # word-stem boost
                                break

                # 3. Concept class preference
                preferred = _PREFERRED_CLASSES.get(effective_domain, set())
                if concept_class in preferred:
                    score -= 0.03
                if concept_class in _PENALIZED_CLASSES:
                    # Skip penalty if concept name closely matches query
                    # (e.g., don't penalize "Malignant neoplasm" when query IS "malignant neoplasm")
                    if name_lower != query_lower and query_lower not in name_lower:
                        score += 0.05

                # 4. Domain mismatch penalty (strong — reduces domain confusion)
                if domain_hint and domain != domain_hint:
                    score += 0.50

                # 5. Standard concept preference (graceful: skip if not in metadata)
                if "standard_concept" in meta:
                    std = meta["standard_concept"]
                    if std == "S":
                        score -= 0.10  # prefer standard concepts
                    elif std is None or std == "":
                        score += 0.15  # penalize non-standard
                    # C (Classification) gets no adjustment (0.0)

                # 6. Common Concept Boost (Reliability / Frequency)
                # Data-driven priority from DB stats + Defaults
                if int(cid) in self.concept_weights:
                    score += self.concept_weights[int(cid)]

                candidates.append(CandidateConcept(
                    concept_id=int(cid),
                    concept_name=concept_name,
                    domain_id=domain,
                    vocabulary_id=vocab,
                    concept_class_id=concept_class,
                    distance=dist,
                    adjusted_score=score,
                ))

        # Sort by adjusted score (lower = better)
        candidates.sort(key=lambda c: c.adjusted_score)
        
        # Return top n_results
        result = candidates[:n_results]
        
        if result and logger.isEnabledFor(logging.DEBUG):
            top = result[0]
            logger.debug(
                f"[Retriever] '{query_text}' → top: {top.concept_name} "
                f"(ID={top.concept_id}, dist={top.distance:.3f}, "
                f"adj={top.adjusted_score:.3f}, vocab={top.vocabulary_id})"
            )
        
        return result

    def _score_candidates(
        self,
        query_text: str,
        ids: List[str],
        metadatas: List[Dict[str, Any]],
        distances: List[float],
        documents: List[str],
        domain_hint: Optional[str],
        n_results: int,
    ) -> List[CandidateConcept]:
        """Score and rank raw ChromaDB results for a single query.

        Applies the same post-retrieval scoring as search():
        vocab preference, exact match boost, class preference,
        domain mismatch penalty, standard concept preference,
        and concept weight boost.
        """
        query_lower = query_text.lower().strip()
        candidates: List[CandidateConcept] = []

        for i, cid in enumerate(ids):
            meta = metadatas[i]
            concept_name = (
                documents[i] if i < len(documents)
                else meta.get("concept_name", "Unknown")
            )
            domain = meta.get("domain_id", "Unknown")
            vocab = meta.get("vocabulary_id", "Unknown")
            concept_class = meta.get("concept_class_id", "Unknown")
            dist = distances[i]

            score = dist

            # 1. Vocabulary preference bonus
            effective_domain = domain_hint or domain
            vocab_prefs = _VOCAB_PREFERENCE.get(effective_domain, {})
            score += vocab_prefs.get(vocab, 0.05)

            # 2. Exact / substring match boost
            name_lower = concept_name.lower()
            if name_lower == query_lower:
                score -= 0.15
            elif query_lower in name_lower:
                score -= 0.08
            elif name_lower in query_lower:
                score -= 0.04
            else:
                query_words = set(query_lower.split())
                name_words = set(name_lower.split())
                for qw in query_words:
                    if len(qw) < 5:
                        continue
                    prefix = qw[:min(len(qw) - 2, 8)]
                    for nw in name_words:
                        if nw.startswith(prefix):
                            score -= 0.06
                            break

            # 3. Concept class preference
            preferred = _PREFERRED_CLASSES.get(effective_domain, set())
            if concept_class in preferred:
                score -= 0.03
            if concept_class in _PENALIZED_CLASSES:
                if name_lower != query_lower and query_lower not in name_lower:
                    score += 0.05

            # 4. Domain mismatch penalty
            if domain_hint and domain != domain_hint:
                score += 0.50

            # 5. Standard concept preference
            if "standard_concept" in meta:
                std = meta["standard_concept"]
                if std == "S":
                    score -= 0.10
                elif std is None or std == "":
                    score += 0.15

            # 6. Common concept boost
            if int(cid) in self.concept_weights:
                score += self.concept_weights[int(cid)]

            candidates.append(CandidateConcept(
                concept_id=int(cid),
                concept_name=concept_name,
                domain_id=domain,
                vocabulary_id=vocab,
                concept_class_id=concept_class,
                distance=dist,
                adjusted_score=score,
            ))

        candidates.sort(key=lambda c: c.adjusted_score)
        return candidates[:n_results]

    def batch_search(
        self,
        query_texts: List[str],
        n_results: int = 60,
        domain_hints: Optional[List[Optional[str]]] = None,
        max_batch_size: int = 50,
    ) -> Dict[str, List[CandidateConcept]]:
        """Batch search ChromaDB for multiple query texts.

        Groups queries by domain_hint to minimize ChromaDB calls
        (one call per unique domain_hint value). Within each group,
        queries are chunked into batches of ``max_batch_size`` to
        avoid exceeding ChromaDB limits. Returns a dict mapping each
        query_text to its list of CandidateConcept results.
        """
        if not query_texts:
            return {}

        effective_batch = int(os.environ.get("CHROMA_BATCH_SIZE", str(max_batch_size)))
        fetch_n = max(n_results * 3, 60)
        hints = domain_hints or [None] * len(query_texts)
        result: Dict[str, List[CandidateConcept]] = {}

        # Group queries by domain_hint
        groups: Dict[Optional[str], List[tuple]] = {}  # hint -> [(index, query_text)]
        for idx, query_text in enumerate(query_texts):
            hint = hints[idx] if idx < len(hints) else None
            groups.setdefault(hint, []).append((idx, query_text))

        for hint, items in groups.items():
            where_clause = {"domain_id": hint} if hint else None

            # Split items into chunks of effective_batch
            for chunk_start in range(0, len(items), effective_batch):
                chunk_items = items[chunk_start:chunk_start + effective_batch]
                texts = [qt for _, qt in chunk_items]

                try:
                    kwargs: Dict[str, Any] = {
                        "query_texts": texts,
                        "n_results": fetch_n,
                        "include": ["metadatas", "distances", "documents"],
                    }
                    if where_clause:
                        kwargs["where"] = where_clause

                    raw = self.collection.query(**kwargs)
                except Exception as e:
                    logger.warning(f"batch_search ChromaDB query failed for hint={hint}: {e}")
                    for _, qt in chunk_items:
                        result[qt] = []
                    continue

                if not raw or not raw.get("ids"):
                    for _, qt in chunk_items:
                        result[qt] = []
                    continue

                for pos, (_, query_text) in enumerate(chunk_items):
                    if pos >= len(raw["ids"]):
                        result[query_text] = []
                        continue

                    ids = raw["ids"][pos]
                    metadatas = raw["metadatas"][pos] if raw.get("metadatas") else [{}] * len(ids)
                    distances = raw["distances"][pos] if raw.get("distances") else [1.0] * len(ids)
                    documents = raw.get("documents", [[]])[pos] if raw.get("documents") else [""] * len(ids)

                    result[query_text] = self._score_candidates(
                        query_text=query_text,
                        ids=ids,
                        metadatas=metadatas,
                        distances=distances,
                        documents=documents,
                        domain_hint=hint,
                        n_results=n_results,
                    )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"[Retriever] batch_search: {len(query_texts)} queries, "
                f"{len(groups)} domain groups, "
                f"{sum(len(v) for v in result.values())} total candidates"
            )

        return result


# Singleton instance for easy import
retriever = ConceptRetriever()
