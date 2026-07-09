#!/usr/bin/env python3
"""
Local test script: pull ONE item's cover photo from production by item ID,
run it through remove.bg background removal + white-background composite,
and save before/after images locally for visual inspection.

READ-ONLY: does not write to the database or upload anything to S3.
Safe to point directly at production.

Usage:
    python test_background_removal.py --item-id 4821
    python test_background_removal.py --item-id 4821 --canvas-size 1600 --fill-ratio 0.8

Requires:
    pip install boto3 psycopg2-binary requests pillow python-dotenv
"""

import argparse
import io
import os

import boto3
import psycopg2
import requests
from PIL import Image, ImageDraw, ImageFilter
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]
REMOVEBG_API_KEY = os.environ["REMOVEBG_API_KEY"]
AWS_ACCESS_KEY_ID = os.environ["AWS_ACCESS_KEY_ID"]
AWS_SECRET_ACCESS_KEY = os.environ["AWS_SECRET_ACCESS_KEY"]
# Adjust this name if your .env uses a different variable for the bucket
AWS_S3_BUCKET_NAME = os.environ["AWS_S3_BUCKET"]
AWS_REGION = os.environ.get("AWS_REGION", "us-east-2")

OUTPUT_DIR = "test_output"


def get_photos_for_item(item_id: int) -> dict:
    """Raw read-only query — deliberately NOT importing app.py/models.py,
    since importing the Flask app would spin up the AI queue worker thread.

    Returns {"cover": <filename>, "gallery": [<filename>, ...]}.
    """
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT photo_url FROM inventory_item WHERE id = %s", (item_id,))
            row = cur.fetchone()
            if row is None:
                raise SystemExit(f"No item found with id={item_id}")
            cover = row[0]

            cur.execute("SELECT photo_url FROM item_photo WHERE item_id = %s", (item_id,))
            gallery = [r[0] for r in cur.fetchall()]

        return {"cover": cover, "gallery": gallery}
    finally:
        conn.close()


def download_from_s3(filename: str) -> bytes:
    s3 = boto3.client(
        "s3",
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=AWS_REGION,
    )
    # storage.py's S3Storage stores every object under an "uploads/" prefix —
    # the DB only holds the bare filename, so the real key needs the prefix added back.
    key = f"uploads/{filename}"
    try:
        buf = io.BytesIO()
        s3.download_fileobj(AWS_S3_BUCKET_NAME, key, buf)
        return buf.getvalue()
    except s3.exceptions.ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code in ("404", "NoSuchKey"):
            print(f"\nCould not find key '{key}' in bucket '{AWS_S3_BUCKET_NAME}'.")
            print("Searching the bucket for similar keys to help diagnose...")
            prefix = "uploads/" + "_".join(filename.split("_")[:2]) + "_"
            resp = s3.list_objects_v2(Bucket=AWS_S3_BUCKET_NAME, Prefix=prefix)
            keys = [obj["Key"] for obj in resp.get("Contents", [])]
            if not keys:
                print(f"Nothing found with prefix '{prefix}' either.")
                print("Trying an unscoped search across the bucket (first 1000 objects)...")
                resp = s3.list_objects_v2(Bucket=AWS_S3_BUCKET_NAME)
                keys = [obj["Key"] for obj in resp.get("Contents", []) if filename in obj["Key"]]

            if keys:
                print("Found these matching key(s) instead:")
                for k in keys:
                    print(f"  {k}")
            else:
                print(
                    f"No matching keys found anywhere in bucket '{AWS_S3_BUCKET_NAME}'. "
                    "Double-check AWS_S3_BUCKET_NAME and AWS_REGION in your .env match exactly "
                    "what's set in Render's environment variables for the live app."
                )
        raise


def remove_background(image_bytes: bytes) -> bytes:
    response = requests.post(
        "https://api.remove.bg/v1.0/removebg",
        files={"image_file": image_bytes},
        data={"size": "auto", "format": "png"},
        headers={"X-Api-Key": REMOVEBG_API_KEY},
        timeout=60,
    )
    if response.status_code == 402:
        raise RuntimeError("remove.bg: out of credits (402 Payment Required)")
    if response.status_code != 200:
        raise RuntimeError(f"remove.bg error {response.status_code}: {response.text}")
    return response.content


def composite_on_white(cutout_png_bytes: bytes, canvas_size: int = 1600, fill_ratio: float = 0.8) -> Image.Image:
    cutout = Image.open(io.BytesIO(cutout_png_bytes)).convert("RGBA")

    # Scale item to fit fill_ratio of canvas, preserving aspect ratio
    target_dim = int(canvas_size * fill_ratio)
    scale = min(target_dim / cutout.width, target_dim / cutout.height)
    new_w, new_h = int(cutout.width * scale), int(cutout.height * scale)
    cutout = cutout.resize((new_w, new_h), Image.LANCZOS)

    canvas = Image.new("RGB", (canvas_size, canvas_size), "white")

    # Centered horizontally; slightly more headroom above than below
    x = (canvas_size - new_w) // 2
    y = int((canvas_size - new_h) * 0.55)

    # Soft drop shadow beneath the item
    shadow = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_box = [
        x + new_w * 0.1, y + new_h * 0.92,
        x + new_w * 0.9, y + new_h * 1.02,
    ]
    shadow_draw.ellipse(shadow_box, fill=(0, 0, 0, 60))
    shadow = shadow.filter(ImageFilter.GaussianBlur(canvas_size * 0.015))
    canvas.paste(shadow, (0, 0), shadow)

    canvas.paste(cutout, (x, y), cutout)
    return canvas


def process_one_photo(label: str, filename: str, item_id: int, dry_run: bool, canvas_size: int, fill_ratio: float) -> str:
    """Returns a short status string for the summary at the end."""
    print(f"\n--- {label}: {filename} ---")

    print("Downloading original from S3...")
    original_bytes = download_from_s3(filename)
    before_path = os.path.join(OUTPUT_DIR, f"{item_id}_{label}_before.jpg")
    with open(before_path, "wb") as f:
        f.write(original_bytes)
    print(f"Saved original -> {before_path}")

    if dry_run:
        print("Dry run: stopping before remove.bg call.")
        return "dry-run (no API call made)"

    try:
        print("Calling remove.bg (uses one paid API credit)...")
        cutout_bytes = remove_background(original_bytes)
    except RuntimeError as e:
        print(f"FAILED: {e}")
        return f"failed — {e}"

    print("Compositing onto white background...")
    final_image = composite_on_white(cutout_bytes, canvas_size, fill_ratio)

    after_path = os.path.join(OUTPUT_DIR, f"{item_id}_{label}_after.jpg")
    final_image.save(after_path, "JPEG", quality=88)
    print(f"Saved processed -> {after_path}")
    return "success"


def main():
    parser = argparse.ArgumentParser(description="Test background removal on one item's photos")
    parser.add_argument("--item-id", type=int, required=True)
    parser.add_argument("--canvas-size", type=int, default=1600)
    parser.add_argument("--fill-ratio", type=float, default=0.8)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Look up the item and download its photos locally, but do NOT call remove.bg. "
             "Use this first to confirm you've got the right item before spending credits.",
    )
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"Looking up item {args.item_id}...")
    photos = get_photos_for_item(args.item_id)
    print(f"Cover: {photos['cover']}")
    print(f"Gallery ({len(photos['gallery'])} photo(s)): {photos['gallery']}")

    # Build an ordered label -> filename map, then dedupe identical filenames
    # (cover and gallery[0] are frequently the same underlying file by design).
    labeled_photos = [("cover", photos["cover"])]
    for i, filename in enumerate(photos["gallery"]):
        labeled_photos.append((f"gallery{i}", filename))

    seen_filenames = {}  # filename -> label that already claimed it
    results = {}
    for label, filename in labeled_photos:
        if filename in seen_filenames:
            original_label = seen_filenames[filename]
            print(f"\n--- {label}: {filename} ---")
            print(f"Identical to '{original_label}' — skipping duplicate remove.bg call.")
            results[label] = f"skipped (duplicate of {original_label})"
            continue
        seen_filenames[filename] = label
        results[label] = process_one_photo(
            label, filename, args.item_id, args.dry_run, args.canvas_size, args.fill_ratio
        )

    print("\n=== Summary ===")
    for label, status in results.items():
        print(f"  {label}: {status}")

    if args.dry_run:
        print("\nDry run complete — no API calls made. Re-run without --dry-run when ready.")
    else:
        print("\nDone. Open the before/after files side by side to check quality.")


if __name__ == "__main__":
    main()