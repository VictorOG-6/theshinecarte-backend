from fastapi import HTTPException, Depends, status
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import select
from datetime import datetime, timezone, timedelta
import jwt
from jwt.exceptions import InvalidTokenError
from models import TokenData, User, UserRole
from database import SessionDep
import secrets
import os
from uuid import UUID

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")

ALGORITHM = os.getenv("ALGORITHM")
SECRET_KEY = os.getenv("SECRET_KEY")

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(days=7)
    to_encode.update({"exp": expire, "type": "refresh"})

    # Add a unique identifier to prevent token reuse
    to_encode.update({"jti": secrets.token_urlsafe(32)})

    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user(
    session: SessionDep, token: str = Depends(oauth2_scheme)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token_data = verify_token(token, "access", credentials_exception)
    user = session.exec(select(User).where(User.email == token_data.username)).first()

    if user is None:
        raise credentials_exception
    return user


async def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


async def get_current_admin_or_staff(
    current_user: User = Depends(get_current_user),
) -> User:
    if current_user.role not in {UserRole.ADMIN, UserRole.STAFF}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin or staff access required",
        )
    return current_user


async def get_current_user_by_id(
    session: SessionDep, token: str = Depends(oauth2_scheme)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token_data = verify_token(token, "access", credentials_exception)
    
    # Convert string user_id back to UUID for database query
    user_id = UUID(token_data.user_id)
    user = session.get(User, user_id)

    if user is None:
        raise credentials_exceptions
    return user

def verify_token(token: str, token_type: str, credentials_exception):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != token_type:
            raise credentials_exception  # Should raise, not return

        email = payload.get("sub")
        user_id = payload.get("user_id")  # This is now a string
        jti = payload.get("jti")

        if email is None or user_id is None:
            raise credentials_exception
        return TokenData(username=email, user_id=user_id, jti=jti)
    except InvalidTokenError:
        raise credentials_exception