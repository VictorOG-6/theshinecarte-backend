import os

from sqlmodel import Session, select

from models import User, UserRole, password_hash


def seed_initial_admin(db: Session, *, email_verified: bool = False) -> User:
    """
    Creates the initial admin user from environment variables.

    Raises:
        ValueError: If required environment variables are missing.
        RuntimeError: If an admin user already exists.
    """
    admin_exists = db.exec(
        select(User).where(User.role == UserRole.ADMIN)
    ).first()

    if admin_exists:
        raise RuntimeError("An admin user already exists.")

    email = os.environ.get("INITIAL_ADMIN_EMAIL")
    password = os.environ.get("INITIAL_ADMIN_PASSWORD")
    name = os.environ.get("INITIAL_ADMIN_NAME", "Admin")

    if not email:
        raise ValueError("INITIAL_ADMIN_EMAIL environment variable is not set.")

    if not password:
        raise ValueError("INITIAL_ADMIN_PASSWORD environment variable is not set.")

    admin = User(
        name=name,
        email=email,
        hashed_password=password_hash.hash(password),
        total_orders=0,
        total_spent=0,
        role=UserRole.ADMIN,
        email_verified=email_verified,
    )

    db.add(admin)
    db.commit()
    db.refresh(admin)

    return admin