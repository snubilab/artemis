from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from src.settings import settings

# Create Engine
# Increase pool headroom for TTE eligibility processing bursts.
# (--workers 2 + ThreadPoolExecutor(16) can generate 30+ concurrent queries)
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=40,
    pool_timeout=60,
    connect_args={"connect_timeout": 3}  # 3-second timeout to avoid hanging
)

# Session Factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()

def get_db():
    """
    Dependency generator for database sessions.
    Usage:
        with get_db() as db:
            db.query(...)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
