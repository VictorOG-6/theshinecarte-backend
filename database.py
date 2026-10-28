from fastapi import Depends
from sqlmodel import create_engine, SQLModel, Session
from typing import Annotated
import os
import re

_ENV_ALIASES = {
    "POSTGRES_USER": ("PGUSER",),
    "POSTGRES_PASSWORD": ("PGPASSWORD",),
    "POSTGRES_HOST": ("PGHOST",),
    "POSTGRES_PORT": ("PGPORT",),
    "POSTGRES_DB": ("PGDATABASE",),
}


def _lookup_env(name: str) -> str | None:
    value = os.getenv(name)
    if value:
        return value
    for alias in _ENV_ALIASES.get(name, ()):
        value = os.getenv(alias)
        if value:
            return value
    if name == "POSTGRES_PORT":
        return "5432"
    return None


def _expand_env_vars(value: str) -> str:
    def replacer(match: re.Match[str]) -> str:
        resolved = _lookup_env(match.group(1))
        return resolved if resolved is not None else match.group(0)

    return re.sub(r"\$\{([^}]+)\}", replacer, value)


def _normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
    return url


def _resolve_database_url() -> str:
    for env_var in ("DATABASE_PRIVATE_URL", "DATABASE_URL"):
        url = os.getenv(env_var)
        if not url:
            continue
        url = _expand_env_vars(url.strip())
        if url and "${" not in url:
            return _normalize_database_url(url)

    raise RuntimeError(
        "DATABASE_URL is missing or contains unresolved variables. "
        "Link a PostgreSQL service in Railway or set DATABASE_URL."
    )


DATABASE_URL = _resolve_database_url()

engine = create_engine(
    DATABASE_URL,
    echo=True,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session

SessionDep = Annotated[Session, Depends(get_session)]