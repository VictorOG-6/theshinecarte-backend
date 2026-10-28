import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import UploadFile, HTTPException, status
from PIL import Image, ImageOps

class ImageService:
    # Configuration. UPLOAD_DIR may point to the root uploads directory or the
    # legacy uploads/profile_images path used by older profile-image uploads.
    _configured_upload_dir = Path(os.getenv("UPLOAD_DIR", "uploads"))
    UPLOAD_ROOT = (
        _configured_upload_dir.parent
        if _configured_upload_dir.name == "profile_images"
        else _configured_upload_dir
    )
    MAX_SIZE_MB = 5
    MAX_SIZE_BYTES = MAX_SIZE_MB * 1024 * 1024
    ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
    ALLOWED_PURPOSES = {"profile", "product", "bundle"}
    MAX_DIMENSIONS = (1024, 1024)  # Max width, height
    THUMBNAIL_SIZE = (200, 200)
    
    def __init__(self):
        self.UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
        for purpose in self.ALLOWED_PURPOSES:
            self.get_upload_dir(purpose).mkdir(parents=True, exist_ok=True)

    def get_upload_dir(self, purpose: str) -> Path:
        """Return the upload directory for a supported image purpose."""
        if purpose not in self.ALLOWED_PURPOSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid image purpose",
            )
        return self.UPLOAD_ROOT / f"{purpose}_images"
    
    def validate_image(self, file: UploadFile) -> None:
        """Validate image file"""
        if not file.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Image file must include a filename",
            )

        ext = Path(file.filename).suffix.lower()
        if ext not in self.ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid file type. Allowed: {', '.join(self.ALLOWED_EXTENSIONS)}"
            )
        
        # Check file size
        file.file.seek(0, 2)  # Seek to end
        file_size = file.file.tell()
        file.file.seek(0)  # Reset to beginning
        
        if file_size > self.MAX_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File too large. Maximum size: {self.MAX_SIZE_MB}MB"
            )

        try:
            with Image.open(file.file) as image:
                image.verify()
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid image file",
            )
        finally:
            file.file.seek(0)
    
    def optimize_image(self, image: Image.Image) -> Image.Image:
        """Resize and optimize image"""
        image = ImageOps.exif_transpose(image)

        # Convert to RGB if necessary (for PNG with transparency)
        if image.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'P':
                image = image.convert('RGBA')
            background.paste(image, mask=image.split()[-1] if image.mode == 'RGBA' else None)
            image = background
        
        # Resize if larger than max dimensions
        if image.width > self.MAX_DIMENSIONS[0] or image.height > self.MAX_DIMENSIONS[1]:
            image.thumbnail(self.MAX_DIMENSIONS, Image.Resampling.LANCZOS)
        
        return image
    
    def save_image(self, file: UploadFile, purpose: str) -> str:
        """
        Save and optimize an image.
        Returns: relative path to saved image under the uploads root.
        """
        self.validate_image(file)
        
        upload_dir = self.get_upload_dir(purpose)
        ext = Path(file.filename).suffix.lower()
        filename = f"{uuid4()}{ext}"
        file_path = upload_dir / filename
        
        try:
            # Read and optimize image
            with Image.open(file.file) as image:
                image = self.optimize_image(image)
                image.save(file_path, quality=85, optimize=True)
            
            # Return relative path (for database storage)
            return str(Path(f"{purpose}_images") / filename)
            
        except Exception as e:
            # Clean up if save fails
            if file_path.exists():
                file_path.unlink()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to process image: {str(e)}"
            )
    
    def delete_image(self, image_url: str) -> None:
        """Delete image file"""
        if not image_url:
            return
        
        try:
            parsed_path = Path(urlparse(image_url).path)
            path_parts = parsed_path.parts

            if "uploads" in path_parts:
                uploads_index = path_parts.index("uploads")
                relative_path = Path(*path_parts[uploads_index + 1:])
            else:
                relative_path = Path(image_url)

            file_path = (self.UPLOAD_ROOT / relative_path).resolve()
            upload_root = self.UPLOAD_ROOT.resolve()
            if upload_root not in file_path.parents:
                return

            if file_path.exists():
                file_path.unlink()
        except Exception as e:
            # Log error but don't raise - deletion failure shouldn't block user operations
            print(f"Failed to delete image {image_url}: {str(e)}")
    
    def get_image_url(self, image_path: Optional[str], base_url: str) -> Optional[str]:
        """Convert stored path to full URL"""
        if not image_path:
            return None
        if image_path.startswith(("http://", "https://")):
            return image_path
        return f"{base_url}/uploads/{image_path}"


image_service = ImageService()