from enum import Enum

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlmodel import SQLModel

from models import User, UserRole
from services.access_token import get_current_user
from services.image_service import image_service


router = APIRouter(prefix="/image", tags=["Images"])


class ImagePurpose(str, Enum):
    PROFILE = "profile"
    PRODUCT = "product"
    BUNDLE = "bundle"


class ImageUploadResponse(SQLModel):
    image_url: str
    image_path: str


@router.post("", response_model=ImageUploadResponse, status_code=status.HTTP_201_CREATED)
def upload_image(
    request: Request,
    purpose: ImagePurpose = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    if (
        purpose in {ImagePurpose.PRODUCT, ImagePurpose.BUNDLE}
        and current_user.role != UserRole.ADMIN
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )

    image_path = image_service.save_image(file, purpose.value)
    base_url = str(request.base_url).rstrip("/")

    return ImageUploadResponse(
        image_url=image_service.get_image_url(image_path, base_url),
        image_path=image_path,
    )