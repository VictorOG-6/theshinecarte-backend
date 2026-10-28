from sqlmodel import Session, select
from models import User, GoogleUser

def get_user_by_google_sub(google_sub: str, session: Session) -> User | None:
    """Retrieve user by Google subject ID"""
    statement = select(User).where(User.google_sub == google_sub)
    return session.exec(statement).first()


def get_user_by_email(email: str, session: Session) -> User | None:
    """Retrieve user by email address"""
    statement = select(User).where(User.email == email)
    return session.exec(statement).first()


def get_or_create_google_user(google_user: GoogleUser, session: Session) -> User:
    """
    Get existing user or create new user from Google OAuth info.

    Strategy:
    1. Check if user exists with this google_sub
    2. If not, check if user exists with this email
    3. If email exists, link google_sub to existing account
    4. Otherwise, create new user
    """
    # First, try to find by google_sub
    existing_user = get_user_by_google_sub(google_user.sub, session)

    if existing_user:
        return existing_user

    # Next, check if user with this email already exists
    user_with_email = get_user_by_email(google_user.email, session)

    if user_with_email:
        # Link Google account to existing user
        user_with_email.google_sub = google_user.sub
        session.add(user_with_email)
        session.commit()
        session.refresh(user_with_email)
        return user_with_email

    # Create new user
    new_user = User(
        email=google_user.email,
        google_sub=google_user.sub,
        name=google_user.name or google_user.email.split('@')[0],        
    )
    session.add(new_user)
    session.commit()
    session.refresh(new_user)
    return new_user