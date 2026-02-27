"""
Storage abstraction for Campus Swap photo uploads.
Supports AWS S3 (production) and local disk (development).
"""
import os
import logging
from io import BytesIO

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

# Image processing constants (match constants.py)
IMAGE_QUALITY = 80
MAX_DIMENSION = 2000


def _process_image(file_obj) -> bytes:
    """
    Process uploaded image: EXIF transpose, resize if needed, convert to JPEG.
    Returns JPEG bytes.
    """
    img = Image.open(file_obj)
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGBA")
    bg = Image.new("RGB", img.size, (255, 255, 255))
    bg.paste(img, (0, 0), img)
    if bg.width > MAX_DIMENSION or bg.height > MAX_DIMENSION:
        if bg.width > bg.height:
            new_width = MAX_DIMENSION
            new_height = int(bg.height * (MAX_DIMENSION / bg.width))
        else:
            new_height = MAX_DIMENSION
            new_width = int(bg.width * (MAX_DIMENSION / bg.height))
        bg = bg.resize((new_width, new_height), Image.Resampling.LANCZOS)
    buf = BytesIO()
    bg.save(buf, "JPEG", quality=IMAGE_QUALITY, optimize=True)
    return buf.getvalue()


class LocalStorage:
    """Store photos on local disk."""

    def __init__(self, upload_folder: str):
        self.upload_folder = upload_folder
        os.makedirs(upload_folder, exist_ok=True)

    def is_s3(self) -> bool:
        return False

    def save_photo(self, file_obj, key: str) -> str:
        """Save photo to disk. Returns key."""
        jpeg_bytes = _process_image(file_obj)
        path = os.path.join(self.upload_folder, key)
        with open(path, "wb") as f:
            f.write(jpeg_bytes)
        return key

    def save_photo_from_bytes(self, data: bytes, key: str) -> str:
        """Save pre-processed JPEG bytes. Returns key."""
        path = os.path.join(self.upload_folder, key)
        with open(path, "wb") as f:
            f.write(data)
        return key

    def save_photo_from_path(self, src_path: str, key: str) -> str:
        """Copy/move file from src_path to storage. Returns key."""
        import shutil
        dst_path = os.path.join(self.upload_folder, key)
        shutil.copy2(src_path, dst_path)
        return key

    def delete_photo(self, key: str) -> bool:
        """Delete photo from disk. Returns True if deleted."""
        path = os.path.join(self.upload_folder, key)
        if os.path.exists(path):
            try:
                os.remove(path)
                return True
            except OSError as e:
                logger.error(f"Error deleting file {path}: {e}", exc_info=True)
                return False
        return False

    def get_photo_url(self, key: str, request_context=None) -> str:
        """Return URL for serving. For local, returns path for url_for."""
        if request_context:
            from flask import url_for
            return url_for("uploaded_file", filename=key, _external=request_context.get("_external", False))
        return f"/uploads/{key}"

    def exists(self, key: str) -> bool:
        return os.path.exists(os.path.join(self.upload_folder, key))

    def get_photo_bytes(self, key: str) -> bytes | None:
        """Load photo bytes from disk. Returns None if not found."""
        path = os.path.join(self.upload_folder, key)
        if not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            return f.read()


class S3Storage:
    """Store photos in AWS S3."""

    def __init__(self, bucket: str, region: str, cdn_url: str = None):
        import boto3
        self.bucket = bucket
        self.region = region
        self.cdn_url = cdn_url.rstrip("/") if cdn_url else None
        self.client = boto3.client("s3", region_name=region)

    def is_s3(self) -> bool:
        return True

    def _key(self, filename: str) -> str:
        """S3 object key with uploads/ prefix."""
        return f"uploads/{filename}"

    def save_photo(self, file_obj, key: str) -> str:
        """Save photo to S3. key is the filename (e.g. item_123_123.jpg). Returns key."""
        s3_key = self._key(key)
        jpeg_bytes = _process_image(file_obj)
        self.client.put_object(
            Bucket=self.bucket,
            Key=s3_key,
            Body=jpeg_bytes,
            ContentType="image/jpeg",
        )
        return key

    def save_photo_from_bytes(self, data: bytes, key: str) -> str:
        """Save pre-processed JPEG bytes to S3. Returns key."""
        s3_key = self._key(key)
        self.client.put_object(
            Bucket=self.bucket,
            Key=s3_key,
            Body=data,
            ContentType="image/jpeg",
        )
        return key

    def save_photo_from_path(self, src_path: str, key: str) -> str:
        """Upload file from local path to S3. Returns key."""
        s3_key = self._key(key)
        with open(src_path, "rb") as f:
            self.client.put_object(
                Bucket=self.bucket,
                Key=s3_key,
                Body=f.read(),
                ContentType="image/jpeg",
            )
        return key

    def delete_photo(self, key: str) -> bool:
        """Delete photo from S3. Returns True if deleted."""
        s3_key = self._key(key)
        try:
            self.client.delete_object(Bucket=self.bucket, Key=s3_key)
            return True
        except Exception as e:
            logger.error(f"Error deleting S3 object {s3_key}: {e}", exc_info=True)
            return False

    def get_photo_url(self, key: str, request_context=None) -> str:
        """Return public URL for the photo."""
        if self.cdn_url:
            return f"{self.cdn_url}/uploads/{key}"
        return f"https://{self.bucket}.s3.{self.region}.amazonaws.com/uploads/{key}"

    def exists(self, key: str) -> bool:
        """Check if object exists in S3."""
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._key(key))
            return True
        except Exception:
            return False

    def get_photo_bytes(self, key: str) -> bytes | None:
        """Load photo bytes from S3. Returns None if not found."""
        try:
            resp = self.client.get_object(Bucket=self.bucket, Key=self._key(key))
            return resp["Body"].read()
        except Exception as e:
            logger.error(f"Failed to get S3 object {key}: {e}", exc_info=True)
            return None


def get_storage():
    """
    Return storage backend based on environment.
    If AWS_S3_BUCKET is set, use S3. Otherwise use local disk.
    """
    bucket = os.environ.get("AWS_S3_BUCKET")
    if bucket:
        region = os.environ.get("AWS_S3_REGION", "us-east-1")
        cdn_url = os.environ.get("AWS_S3_CDN_URL")
        return S3Storage(bucket=bucket, region=region, cdn_url=cdn_url)
    # Local: use UPLOAD_FOLDER from app config or default
    upload_folder = os.environ.get("UPLOAD_FOLDER")
    if not upload_folder:
        if os.path.exists("/var/data"):
            upload_folder = "/var/data"
        else:
            upload_folder = "static/uploads"
    return LocalStorage(upload_folder=upload_folder)


# Module-level storage instance (initialized when app loads)
_storage = None


def init_storage(app):
    """Initialize storage with app config. Call from app factory/startup."""
    global _storage
    bucket = os.environ.get("AWS_S3_BUCKET")
    if bucket:
        region = os.environ.get("AWS_S3_REGION", "us-east-1")
        cdn_url = os.environ.get("AWS_S3_CDN_URL")
        _storage = S3Storage(bucket=bucket, region=region, cdn_url=cdn_url)
    else:
        upload_folder = app.config.get("UPLOAD_FOLDER", "static/uploads")
        _storage = LocalStorage(upload_folder=upload_folder)
    return _storage


def get_storage_instance():
    """Get the initialized storage instance. Must call init_storage first."""
    return _storage
