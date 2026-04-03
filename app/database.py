import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# DATABASE_URL can be any SQLAlchemy-compatible URL.
# Defaults to a local SQLite file for development convenience.
# In production, set DATABASE_URL=postgresql://user:pass@host:5432/caams
_DEFAULT_SQLITE = f"sqlite:///{Path(__file__).parent.parent / 'caams.db'}"
DATABASE_URL = os.environ.get("DATABASE_URL", _DEFAULT_SQLITE)

# check_same_thread is only required for SQLite
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

_pool_kwargs = (
    {}
    if DATABASE_URL.startswith("sqlite")
    else {
        "pool_size": 10,
        "max_overflow": 20,
        "pool_pre_ping": True,
        "pool_recycle": 1800,
    }
)

engine = create_engine(DATABASE_URL, connect_args=_connect_args, **_pool_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
