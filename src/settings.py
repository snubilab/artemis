import os
from pydantic import ConfigDict
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    # extra="ignore": .env legitimately holds keys other SDKs read from os.environ
    # (google_cloud_project, aws_bearer_token_bedrock, ...); don't crash on them.
    model_config = ConfigDict(env_file=".env", extra="ignore")

    # App
    APP_NAME: str = "ARTEMIS 3.1"
    DEBUG: bool = True
    JSON_LOGS: bool = False  # True for production (JSON output)

    # Pipeline Mode: "run" (default) / "benchmark" / "evaluate"
    PIPELINE_MODE: str = os.getenv("PIPELINE_MODE", "run")
    BENCHMARK_TROY_PATH: str = os.getenv("BENCHMARK_TROY_PATH", "")

    # LLM - OpenRouter (recommended) or direct API
    OPENROUTER_API_KEY: str | None = os.getenv("OPENROUTER_API_KEY")
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    
    # Fallback: Direct API keys
    GOOGLE_API_KEY: str | None = os.getenv("GOOGLE_API_KEY")
    OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")
    
    # Azure AI Foundry (Azure OpenAI)
    AZURE_API_KEY: str | None = os.getenv("AZURE_API_KEY")
    AZURE_ENDPOINT: str | None = os.getenv("AZURE_ENDPOINT")
    AZURE_API_VERSION: str = os.getenv("AZURE_API_VERSION", "2024-06-01")

    # vLLM (OpenAI-compatible self-hosted)
    VLLM_BASE_URL: str | None = os.getenv("VLLM_BASE_URL")  # e.g. http://host:8001/v1
    VLLM_API_KEY: str | None = os.getenv("VLLM_API_KEY", "EMPTY")

    # Default model (OpenRouter format or direct)
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o")
    LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.0"))
    LLM_SEED: int | None = int(os.getenv("LLM_SEED", "42")) if os.getenv("LLM_SEED", "42") else None

    # Database (PostgreSQL)
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://postgres:mypass@localhost:5432/ohdsi")

    # OMOP DB connection params (used by kg_expander, drug_class_expander)
    OMOP_DB_HOST: str = os.getenv("OMOP_DB_HOST", "localhost")
    OMOP_DB_PORT: str = os.getenv("OMOP_DB_PORT", "5432")
    OMOP_DB_NAME: str = os.getenv("OMOP_DB_NAME", "ohdsi")
    OMOP_DB_USER: str = os.getenv("OMOP_DB_USER", "postgres")
    OMOP_DB_PASS: str = os.getenv("OMOP_DB_PASS", "mypass")

    # Vector DB (ChromaDB)
    CHROMA_URL: str | None = os.getenv("CHROMA_URL")
    CHROMA_PERSIST_DIRECTORY: str = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "chroma_db"
    )
    
    # Embedding Model Selection (for ablation)
    # Options: "default" (all-MiniLM-L6-v2), "medcpt" (ncbi/MedCPT)
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "default")
    MEDCPT_DEVICE: str = os.getenv("MEDCPT_DEVICE", "cpu")
    
    # Redis (Optional)
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # =========================================================================
    # Phase 8 P2: Centralized ConceptSet Settings
    # =========================================================================
    
    # OMOP CDM Schema
    CDM_SCHEMA: str = os.getenv("CDM_SCHEMA", "synthea23m")
    
    # PHOEBE (Phenotype Recommender)
    PHOEBE_SCHEMA: str = os.getenv("PHOEBE_SCHEMA", "demo_cdm")
    PHOEBE_TIMEOUT_MS: int = int(os.getenv("PHOEBE_TIMEOUT_MS", "500"))
    
    # RAG Search (ChromaDB)
    RAG_COLLECTION_NAME: str = os.getenv("RAG_COLLECTION_NAME", "omop_concepts")
    RAG_TOP_K: int = int(os.getenv("RAG_TOP_K", "20"))
    
    # Stage 1 Pipeline
    STAGE1_MAX_WORKERS: int = int(os.getenv("STAGE1_MAX_WORKERS", "2"))
    STAGE1_TIMEOUT: float = float(os.getenv("STAGE1_TIMEOUT", "5.0"))
    
    # Clinical Reranker
    RERANKER_CONFIDENCE_THRESHOLD: float = float(os.getenv("RERANKER_CONFIDENCE_THRESHOLD", "0.7"))
    RERANKER_MODEL_NAME: str = os.getenv("RERANKER_MODEL_NAME", "michiyasunaga/BioLinkBERT-base")
    RERANKER_CROSS_ENCODER_MODEL: str = os.getenv("RERANKER_CROSS_ENCODER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
    
    # Cache (Phase 8 P3)
    CACHE_ENABLED: bool = os.getenv("CACHE_ENABLED", "true").lower() == "true"
    CACHE_TTL_SECONDS: int = int(os.getenv("CACHE_TTL_SECONDS", "604800"))  # 7 days
    REDIS_CACHE_PREFIX: str = os.getenv("REDIS_CACHE_PREFIX", "artemis:conceptset:")

settings = Settings()
