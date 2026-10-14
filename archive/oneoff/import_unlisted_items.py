#!/usr/bin/env python3
"""
Campus Swap — Import Unlisted Items to Production
==================================================
Uploads photos to S3 and inserts InventoryItem rows directly into prod Postgres
for items Campus Swap owns outright (donated/unclaimed, no seller account).

Each item is created with:
  - seller_id = 271 (Campus Swap internal account)
  - status = 'pending_valuation'
  - ai_generated_at = NULL  → eligible for AI autofill on next run
  - ai_review_pending = False (AI generate run will set this)
  - storage_location_id = from CSV
  - is_quick_capture = True
  - description = placeholder (AI will overwrite)
  - quality = 3 (neutral default; AI doesn't set this)

After running this script:
  1. Go to /admin/ai/generate and run the AI autofill
  2. Items will appear in /admin/ai/review for your approval
  3. Approve → items go live in the shop

Usage:
    python3 import_unlisted_items.py

Setup (one-time):
    pip install psycopg2-binary boto3 pillow python-dotenv

Input:
    - unlisted_items/         Folder of photos (1.jpg ... 75.jpg)
    - unlisted_items.csv      Two columns: filename, storage_unit
                              e.g.  1.jpg,302
    - .env                    Must contain: RENDER_DATABASE_URL, AWS_S3_BUCKET,
                              AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
                              AWS_S3_REGION (optional, default us-east-1)
"""

import os
import sys
import csv
import io
import uuid
import time
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv

# ── Dependencies ──────────────────────────────────────────────────────────────

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    sys.exit("Missing: pip install psycopg2-binary")

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    sys.exit("Missing: pip install boto3")

try:
    from PIL import Image
except ImportError:
    sys.exit("Missing: pip install pillow")

# ── Config ────────────────────────────────────────────────────────────────────

load_dotenv()

RENDER_DATABASE_URL = os.getenv("RENDER_DATABASE_URL")
AWS_S3_BUCKET       = os.getenv("AWS_S3_BUCKET")
AWS_REGION          = os.getenv("AWS_S3_REGION", "us-east-1")

PHOTOS_DIR  = Path("unlisted_items")
INPUT_CSV = Path("unlisted_items_remaining.csv")

# Campus Swap internal account (user id=271, internal@campusswap.com)
CAMPUS_SWAP_SELLER_ID = 271

# Placeholder description — AI autofill will replace this
PLACEHOLDER_DESCRIPTION = "Item pending AI review"

# Default quality score (1–5 scale; 3 = average)
DEFAULT_QUALITY = 3

# Set to None to import all rows, or a number for a test run (e.g. 3)
MAX_ITEMS = None

# ── Validation ────────────────────────────────────────────────────────────────

def validate_setup():
    errors = []
    if not RENDER_DATABASE_URL:
        errors.append("RENDER_DATABASE_URL not set in .env")
    if not AWS_S3_BUCKET:
        errors.append("AWS_S3_BUCKET not set in .env")
    if not os.getenv("AWS_ACCESS_KEY_ID"):
        errors.append("AWS_ACCESS_KEY_ID not set in .env")
    if not os.getenv("AWS_SECRET_ACCESS_KEY"):
        errors.append("AWS_SECRET_ACCESS_KEY not set in .env")
    if not PHOTOS_DIR.exists():
        errors.append(f"Photos folder not found: {PHOTOS_DIR}/")
    if not INPUT_CSV.exists():
        errors.append(f"CSV not found: {INPUT_CSV}  (columns: filename,storage_unit)")
    if errors:
        print("Setup errors:")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)
    print("✓ Setup looks good\n")

# ── Image helpers ─────────────────────────────────────────────────────────────

def prepare_image(path: Path) -> bytes:
    """Load image, convert to RGB JPEG. No resize — keep full quality for AI."""
    img = Image.open(path).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()

# ── S3 ────────────────────────────────────────────────────────────────────────

def upload_to_s3(s3_client, img_bytes: bytes, filename: str) -> str:
    """
    Upload image bytes to S3 under uploads/<filename>.
    Returns the filename (not the full key) — matches how photo_url is stored in DB.
    """
    key = f"uploads/{filename}"
    s3_client.put_object(
        Bucket=AWS_S3_BUCKET,
        Key=key,
        Body=img_bytes,
        ContentType="image/jpeg",
    )
    return filename  # DB stores just the filename, not the full key

# ── Database ──────────────────────────────────────────────────────────────────

def connect_prod() -> psycopg2.extensions.connection:
    try:
        conn = psycopg2.connect(RENDER_DATABASE_URL)
        print("✓ Connected to prod DB")
        return conn
    except Exception as e:
        sys.exit(f"Could not connect to prod DB: {e}")


def verify_internal_account(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, email FROM \"user\" WHERE id = %s AND is_internal_account = TRUE",
            (CAMPUS_SWAP_SELLER_ID,)
        )
        row = cur.fetchone()
    if row:
        print(f"✓ Internal account confirmed: id={row[0]}, email={row[1]}")
        return True
    print(f"✗ No internal account found with id={CAMPUS_SWAP_SELLER_ID}")
    return False


def get_storage_location_id(conn, unit_name: str) -> int | None:
    """Look up storage_location.id by name (e.g. '302')."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM storage_location WHERE name = %s LIMIT 1",
            (unit_name.strip(),)
        )
        row = cur.fetchone()
    return row[0] if row else None


def insert_item(conn, photo_url: str, storage_location_id: int | None) -> int:
    """
    Insert one InventoryItem row. Returns the new item id.
    All AI fields left NULL/default so the autofill pipeline picks it up.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)  # store as UTC naive
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO inventory_item (
                description,
                quality,
                status,
                date_added,
                seller_id,
                photo_url,
                storage_location_id,
                is_quick_capture,
                payout_sent,
                ai_generated_at,
                ai_review_pending,
                ai_approved,
                needs_new_photo,
                needs_photo_verification,
                ai_photo_enhanced,
                was_previously_approved
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                TRUE,   -- is_quick_capture
                FALSE,  -- payout_sent
                NULL,   -- ai_generated_at = NULL → eligible for autofill
                FALSE,  -- ai_review_pending (autofill run sets this)
                FALSE,  -- ai_approved
                FALSE,  -- needs_new_photo
                FALSE,  -- needs_photo_verification
                FALSE,  -- ai_photo_enhanced
                FALSE   -- was_previously_approved
            )
            RETURNING id
        """, (
            PLACEHOLDER_DESCRIPTION,
            DEFAULT_QUALITY,
            'pending_valuation',
            now,
            CAMPUS_SWAP_SELLER_ID,
            photo_url,
            storage_location_id,
        ))
        new_id = cur.fetchone()[0]
    conn.commit()
    return new_id

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    validate_setup()

    # Load CSV
    rows = []
    with open(INPUT_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            filename = row.get("filename", "").strip()
            storage_unit = row.get("storage_unit", "").strip()
            if filename:
                rows.append({"filename": filename, "storage_unit": storage_unit})

    if not rows:
        sys.exit("No rows found in unlisted_items.csv")

    if MAX_ITEMS is not None:
        rows = rows[:MAX_ITEMS]
        print(f"Limiting to first {MAX_ITEMS} items (MAX_ITEMS is set)\n")

    print(f"Loaded {len(rows)} items from CSV\n")

    # Connect to prod
    conn = connect_prod()
    if not verify_internal_account(conn):
        conn.close()
        sys.exit("Aborting — internal account check failed.")
    print()

    # Cache storage location lookups to avoid repeated queries
    location_cache: dict[str, int | None] = {}

    # Set up S3
    s3 = boto3.client(
        "s3",
        region_name=AWS_REGION,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )

    success_count = 0
    error_count = 0
    skipped_units = set()

    for i, row in enumerate(rows):
        filename = row["filename"]
        storage_unit = row["storage_unit"]
        photo_path = PHOTOS_DIR / filename

        print(f"[{i+1}/{len(rows)}] {filename} → unit {storage_unit or '(none)'}")

        # Check photo exists
        if not photo_path.exists():
            print(f"  ✗ Photo not found: {photo_path} — skipping")
            error_count += 1
            continue

        # Resolve storage location ID
        if storage_unit not in location_cache:
            location_cache[storage_unit] = get_storage_location_id(conn, storage_unit)
            if location_cache[storage_unit] is None and storage_unit:
                skipped_units.add(storage_unit)
                print(f"  ⚠ Storage unit '{storage_unit}' not found in DB — item will be unassigned")

        storage_location_id = location_cache.get(storage_unit)

        # Prepare image
        try:
            img_bytes = prepare_image(photo_path)
        except Exception as e:
            print(f"  ✗ Could not read image: {e} — skipping")
            error_count += 1
            continue

        # Generate a unique S3 filename that won't collide with existing items
        # Pattern: unlisted_<timestamp>_<uuid4 short>.jpg
        ts = int(time.time())
        uid = uuid.uuid4().hex[:8]
        s3_filename = f"unlisted_{ts}_{uid}.jpg"

        # Upload to S3
        try:
            upload_to_s3(s3, img_bytes, s3_filename)
            print(f"  ✓ Uploaded to S3: uploads/{s3_filename}")
        except Exception as e:
            print(f"  ✗ S3 upload failed: {e} — skipping")
            error_count += 1
            continue

        # Insert DB row
        try:
            item_id = insert_item(conn, s3_filename, storage_location_id)
            print(f"  ✓ Created item #{item_id}")
            success_count += 1
        except Exception as e:
            print(f"  ✗ DB insert failed: {e} — skipping")
            error_count += 1
            # Try to clean up the S3 upload we just made
            try:
                s3.delete_object(Bucket=AWS_S3_BUCKET, Key=f"uploads/{s3_filename}")
            except Exception:
                pass
            continue

    conn.close()

    print(f"\n{'='*50}")
    print(f"Done.")
    print(f"  ✓ {success_count} items created in prod")
    if error_count:
        print(f"  ✗ {error_count} items failed (see above)")
    if skipped_units:
        print(f"  ⚠ Unknown storage units (items created but unassigned): {', '.join(sorted(skipped_units))}")
    print(f"\nNext step: go to /admin/ai/generate and run the AI autofill.")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
