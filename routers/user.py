from fastapi import APIRouter, Depends, HTTPException, status, Request, UploadFile, File, Query
from sqlmodel import select, col
from sqlalchemy.orm import selectinload
from models import UserRead, User, UserCreate, password_hash, UserRegisterResponse, UserUpdate, UserRole, Order, OrderItem, EmailVerification
from datetime import datetime, timezone, timedelta
from database import SessionDep
from services.access_token import get_current_user, get_current_admin
from services.email import send_verification_email
from services.image_service import image_service
from services.otp import generate_otp
from typing import Optional

router = APIRouter(prefix="/user", tags=["Users"])


def build_user_response(user: User, request: Request) -> UserRead:
    user_response = UserRead.model_validate(user)
    if user.profile_image_url:
        base_url = str(request.base_url).rstrip('/')
        user_response.profile_image_url = image_service.get_image_url(
            user.profile_image_url,
            base_url
        )
    return user_response

@router.post("", response_model=UserRegisterResponse, status_code=status.HTTP_201_CREATED)
async def create_user(user: UserCreate, session: SessionDep):
    existing_user = session.exec(select(User).where(User.email == user.email)).first()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already reistered"
        )

    hashed_pwd = password_hash.hash(user.password)
    new_user = User(name=user.name, email=user.email, hashed_password=hashed_pwd)
    session.add(new_user)
    session.commit()
    session.refresh(new_user)

    otp = generate_otp()

    verification = EmailVerification(
        user_id=new_user.id,
        otp_hash=password_hash.hash(otp),
        expires_at=(datetime.now(timezone.utc) + timedelta(minutes=10)),
        attempts=0,
        used=False,
    )

    session.add(verification)
    session.commit()

    await send_verification_email(email=new_user.email, user_name=new_user.name, otp=otp)

    return { "message": "Account created. Please verify your email.", "user": new_user, }

@router.patch("", response_model=UserRead)
def update_user(
    request: Request,
    user_update: UserUpdate,
    session: SessionDep,
    current_user: User = Depends(get_current_user)
):
    """Update user profile information"""
    user_data = user_update.model_dump(exclude_unset=True)
    
    # Check email uniqueness if updating email
    if "email" in user_data:
        existing = session.exec(
            select(User).where(
                User.email == user_data["email"],
                User.id != current_user.id
            )
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already in use"
            )
    
    for key, value in user_data.items():
        setattr(current_user, key, value)
    
    session.add(current_user)
    session.commit()
    session.refresh(current_user)
    
    return build_user_response(current_user, request)

@router.post("/profile-image")
def upload_profile_image(
    request: Request,
    session: SessionDep,
    current_user: User = Depends(get_current_user),
    file: UploadFile = File(...),
):
    """Upload or update user profile image"""
    # Delete old image if exists
    if current_user.profile_image_url:
        image_service.delete_image(current_user.profile_image_url)
    
    # Save new image
    image_path = image_service.save_image(file, "profile")
    
    # Update user record
    current_user.profile_image_url = image_path
    session.add(current_user)
    session.commit()
    session.refresh(current_user)
    
    # Return full URL
    base_url = str(request.base_url).rstrip('/')
    full_url = image_service.get_image_url(image_path, base_url)
    
    return {
        "message": "Profile image uploaded successfully",
        "profile_image_url": full_url
    }


@router.delete("/profile-image", status_code=status.HTTP_204_NO_CONTENT)
def delete_profile_image(
    session: SessionDep,
    current_user: User = Depends(get_current_user)
):
    """Delete user profile image"""
    if not current_user.profile_image_url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No profile image found"
        )
    
    # Delete image file
    image_service.delete_image(current_user.profile_image_url)
    
    # Update user record
    current_user.profile_image_url = None
    session.add(current_user)
    session.commit()
    
    return None

@router.get("", response_model=UserRead)
def get_user(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    return build_user_response(current_user, request)

@router.get("/all", response_model=list[UserRead])
def get_users(
    request: Request,
    session: SessionDep,
    current_admin: User = Depends(get_current_admin),
    page: int = Query(1, description="Page number", ge=1),
    page_size: int = Query(10, description="Number of items per page", ge=1, le=100),
    name: Optional[str] = Query(None, description="Filter users by name (partial match)"),
    email: Optional[str] = Query(None, description="Filter users by email (partial match)"),
    role: Optional[UserRole] = Query(None, description="Filter users by role"),
):
    statement = (
        select(User)
        .options(
            selectinload(User.orders)
            .selectinload(Order.order_items)
            .selectinload(OrderItem.product),
            selectinload(User.orders)
            .selectinload(Order.order_items)
            .selectinload(OrderItem.product_variant),
            selectinload(User.orders)
            .selectinload(Order.order_items)
            .selectinload(OrderItem.product_sub_variant),
        )
        .order_by(User.created_at.desc())
    )

    if name:
        statement = statement.where(col(User.name).contains(name))

    if email:
        statement = statement.where(col(User.email).contains(email))

    if role:
        statement = statement.where(User.role == role)

    offset = (page - 1) * page_size
    statement = statement.offset(offset).limit(page_size)

    users = session.exec(statement).all()
    return [build_user_response(user, request) for user in users]