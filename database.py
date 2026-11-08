from fastapi import Depends
from sqlmodel import create_engine, SQLModel, Session
from typing import Annotated
from urllib.parse import quote_plus
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


def _build_database_url_from_parts() -> str | None:
    user = _lookup_env("POSTGRES_USER")
    password = _lookup_env("POSTGRES_PASSWORD")
    host = _lookup_env("POSTGRES_HOST")
    port = _lookup_env("POSTGRES_PORT")
    db = _lookup_env("POSTGRES_DB")
    if not all((user, password, host, db)):
        return None
    safe_user = quote_plus(user)
    safe_password = quote_plus(password)
    return f"postgresql://{safe_user}:{safe_password}@{host}:{port}/{db}"


def _resolve_database_url() -> str:
    # Railway: DATABASE_PRIVATE_URL (in-network), DATABASE_URL, DATABASE_PUBLIC_URL
    for env_var in (
        "DATABASE_PRIVATE_URL",
        "DATABASE_URL",
        "DATABASE_PUBLIC_URL",
    ):
        url = os.getenv(env_var)
        if not url:
            continue
        url = _expand_env_vars(url.strip())
        if url and "${" not in url and not url.startswith("${{"):
            return _normalize_database_url(url)

    built = _build_database_url_from_parts()
    if built:
        return built

    raise RuntimeError(
        "DATABASE_URL is missing or contains unresolved variables. "
        "On your Railway app service (not the Postgres service), add a variable "
        "reference to the linked Postgres DATABASE_URL or DATABASE_PRIVATE_URL, "
        "or set a full postgresql:// URL. Do not paste raw ${{Postgres...}} "
        "templates; use Railway's 'Add Reference' control."
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