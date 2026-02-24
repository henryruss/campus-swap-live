#!/usr/bin/env python3
"""
One-time migration: Upload existing photos from local disk to S3.

Run this after deploying S3 support but before removing the Render persistent disk.
Requires: AWS_S3_BUCKET, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY (or default creds)
Optional: AWS_S3_REGION (default us-east-1)

Usage:
  # From project root, with .env or env vars set:
  python scripts/migrate_photos_to_s3.py

  # Specify local folder (default: /var/data or static/uploads)
  python scripts/migrate_photos_to_s3.py --folder /path/to/photos

  # Delete from disk after successful upload (use with caution)
  python scripts/migrate_photos_to_s3.py --delete-after
"""
import os
import sys
import argparse

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

if not os.environ.get("AWS_S3_BUCKET"):
    print("Error: AWS_S3_BUCKET must be set. Add it to .env or export it.")
    sys.exit(1)

from app import app
from models import InventoryItem, ItemPhoto
from storage import S3Storage


def main():
    parser = argparse.ArgumentParser(description="Migrate photos from disk to S3")
    parser.add_argument("--folder", help="Local folder containing photos (default: /var/data or static/uploads)")
    parser.add_argument("--delete-after", action="store_true", help="Delete from disk after successful upload")
    parser.add_argument("--dry-run", action="store_true", help="List files that would be migrated without uploading")
    args = parser.parse_args()

    folder = args.folder
    if not folder:
        folder = "/var/data" if os.path.exists("/var/data") else "static/uploads"
    if not os.path.isdir(folder):
        print(f"Error: Folder {folder} does not exist.")
        sys.exit(1)

    bucket = os.environ.get("AWS_S3_BUCKET")
    region = os.environ.get("AWS_S3_REGION", "us-east-1")
    s3 = S3Storage(bucket=bucket, region=region)

    with app.app_context():
        # Collect all unique photo filenames
        filenames = set()
        for item in InventoryItem.query.all():
            if item.photo_url and item.photo_url.strip():
                filenames.add(item.photo_url.strip())
        for photo in ItemPhoto.query.all():
            if photo.photo_url and photo.photo_url.strip():
                filenames.add(photo.photo_url.strip())

        print(f"Found {len(filenames)} unique photo filenames in database.")
        if not filenames:
            print("Nothing to migrate.")
            return

        migrated = 0
        skipped_s3 = 0
        skipped_missing = 0
        errors = 0

        for fn in sorted(filenames):
            local_path = os.path.join(folder, fn)
            if not os.path.exists(local_path):
                skipped_missing += 1
                if args.dry_run:
                    print(f"  [MISSING] {fn}")
                continue

            if s3.exists(fn):
                skipped_s3 += 1
                if args.dry_run:
                    print(f"  [EXISTS] {fn}")
                continue

            if args.dry_run:
                print(f"  [WOULD UPLOAD] {fn}")
                migrated += 1
                continue

            try:
                s3.save_photo_from_path(local_path, fn)
                migrated += 1
                print(f"  Uploaded: {fn}")
                if args.delete_after:
                    os.remove(local_path)
                    print(f"    Deleted from disk")
            except Exception as e:
                errors += 1
                print(f"  ERROR {fn}: {e}", file=sys.stderr)

        print(f"\nDone. Migrated: {migrated}, Already in S3: {skipped_s3}, Missing: {skipped_missing}, Errors: {errors}")


if __name__ == "__main__":
    main()
