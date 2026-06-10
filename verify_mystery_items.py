#!/usr/bin/env python3
"""
Campus Swap — Mystery Item Verification Script
==============================================
Compares photos of unassigned "mystery" items against DB items that have no
storage_location_id, to check whether any mystery item is actually a seller
listing we just couldn't match manually.

Usage:
    python verify_mystery_items.py

Setup (one-time):
    pip install anthropic psycopg2-binary boto3 pillow python-dotenv

Input:
    - mystery_items/          Folder of photos named 1.jpg, 2.jpg, etc.
                              (or any numbering — sorted numerically)
    - .env                    Must contain: ANTHROPIC_API_KEY, AWS_S3_BUCKET,
                              AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
                              AWS_S3_REGION (optional, defaults to us-east-1)

Output:
    - report.html             Open in browser. Shows each mystery item and
                              any flagged DB candidates side by side.
"""

import os
import sys
import json
import base64
import io
import time
import re
from pathlib import Path
from dotenv import load_dotenv

# ── Dependencies ─────────────────────────────────────────────────────────────

try:
    import anthropic
except ImportError:
    sys.exit("Missing: pip install anthropic")

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

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
AWS_S3_BUCKET     = os.getenv("AWS_S3_BUCKET")
AWS_REGION        = os.getenv("AWS_S3_REGION", "us-east-1")
LOCAL_DB          = os.getenv("LOCAL_DB_NAME", "campusswap")

MYSTERY_PHOTOS_DIR = Path("unlisted_items")
REPORT_OUTPUT      = Path("report.html")

MODEL = "claude-haiku-4-5"

# How many DB candidate photos to send per API call (keep under token limit)
MAX_CANDIDATES_PER_CALL = 12

# Set to None to process all items, or a number to limit (e.g. 3 for a test run)
MAX_ITEMS = None

# Max image dimension (pixels) — resize before sending to save tokens
MAX_IMAGE_DIM = 800

# ── Validation ────────────────────────────────────────────────────────────────

def validate_setup():
    errors = []
    if not ANTHROPIC_API_KEY:
        errors.append("ANTHROPIC_API_KEY not set in .env")
    if not AWS_S3_BUCKET:
        errors.append("AWS_S3_BUCKET not set in .env")
    if not os.getenv("AWS_ACCESS_KEY_ID"):
        errors.append("AWS_ACCESS_KEY_ID not set in .env")
    if not os.getenv("AWS_SECRET_ACCESS_KEY"):
        errors.append("AWS_SECRET_ACCESS_KEY not set in .env")
    if not MYSTERY_PHOTOS_DIR.exists():
        errors.append(f"Photo folder not found: {MYSTERY_PHOTOS_DIR}/")
    if errors:
        print("Setup errors:")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)
    print("✓ Setup looks good\n")

# ── Image helpers ─────────────────────────────────────────────────────────────

def resize_image_bytes(img_bytes: bytes, max_dim: int = MAX_IMAGE_DIM) -> bytes:
    """Resize an image so its longest side <= max_dim. Returns JPEG bytes."""
    img = Image.open(io.BytesIO(img_bytes))
    img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > max_dim:
        scale = max_dim / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def load_local_image(path: Path) -> bytes | None:
    """Load and resize a local image file."""
    try:
        raw = path.read_bytes()
        return resize_image_bytes(raw)
    except Exception as e:
        print(f"  ⚠ Could not load {path}: {e}")
        return None


def fetch_s3_image(s3_client, filename: str) -> bytes | None:
    """Fetch a photo from S3 by filename and return resized JPEG bytes."""
    try:
        resp = s3_client.get_object(Bucket=AWS_S3_BUCKET, Key=filename)
        raw = resp["Body"].read()
        return resize_image_bytes(raw)
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("NoSuchKey", "404"):
            return None
        print(f"  ⚠ S3 error for {filename}: {e}")
        return None
    except Exception as e:
        print(f"  ⚠ Could not fetch {filename}: {e}")
        return None


def image_to_b64(img_bytes: bytes) -> str:
    return base64.standard_b64encode(img_bytes).decode("utf-8")

# ── Database ──────────────────────────────────────────────────────────────────

def get_candidates(db_conn) -> list[dict]:
    """
    Return all InventoryItems that:
      - have no storage_location_id (unassigned — possibly matching a mystery item)
      - are not rejected or sold
      - have a photo_url
    """
    with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT
                ii.id,
                ii.description,
                ii.seller_description,
                ii.ai_description,
                ii.photo_url,
                ii.status,
                c.name AS category_name
            FROM inventory_item ii
            LEFT JOIN inventory_category c ON c.id = ii.category_id
            WHERE ii.storage_location_id IS NULL
              AND ii.status NOT IN ('rejected', 'sold')
              AND ii.photo_url IS NOT NULL
            ORDER BY ii.id
        """)
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def connect_db() -> psycopg2.extensions.connection:
    try:
        conn = psycopg2.connect(dbname=LOCAL_DB, host="localhost")
        print(f"✓ Connected to local DB: {LOCAL_DB}")
        return conn
    except Exception as e:
        sys.exit(f"Could not connect to local DB '{LOCAL_DB}': {e}\n"
                 "Make sure you've restored the prod snapshot:\n"
                 "  psql {LOCAL_DB} < prod_snapshot.sql")

# ── AI Calls ──────────────────────────────────────────────────────────────────

def identify_mystery_item(client, mystery_b64: str, description: str) -> dict:
    """
    Pass 1: Ask the model what the mystery item is.
    Returns {"item_type": str, "category": str, "color": str, "details": str}
    """
    prompt = f"""You are looking at a photo of an item from a college student's dorm room.
The person cataloguing it labeled it: "{description or 'no label provided'}"

Identify the item. Respond with ONLY a JSON object (no markdown, no explanation):
{{
  "item_type": "short name, e.g. 'mini fridge' or 'wooden dresser'",
  "category": "one of: furniture, appliance, electronics, decor, other",
  "color": "primary color(s)",
  "details": "2-3 distinguishing features: brand if visible, size, style, condition notes"
}}"""

    resp = client.messages.create(
        model=MODEL,
        max_tokens=300,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": mystery_b64}},
                {"type": "text", "text": prompt}
            ]
        }]
    )
    text = resp.content[0].text.strip()
    # Strip any accidental markdown fences
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"item_type": description or "unknown", "category": "other", "color": "unknown", "details": text}


def compare_against_candidates(
    client,
    mystery_b64: str,
    mystery_info: dict,
    candidates: list[dict],
    candidate_images: dict[int, str]  # item_id → b64
) -> list[dict]:
    """
    Pass 2: Compare the mystery item photo against a batch of DB candidates.
    Returns list of {"item_id": int, "confidence": "high|medium|low", "reason": str}
    for any candidates that look like possible matches. Empty list = no match.
    """
    if not candidates:
        return []

    # Build the content array: mystery photo first, then candidates
    content = [
        {"type": "text", "text": (
            f"I have a mystery item that needs to be matched against seller listings in a consignment database.\n\n"
            f"MYSTERY ITEM (first image below):\n"
            f"- Type: {mystery_info.get('item_type', 'unknown')}\n"
            f"- Category: {mystery_info.get('category', 'unknown')}\n"
            f"- Color: {mystery_info.get('color', 'unknown')}\n"
            f"- Details: {mystery_info.get('details', 'none')}\n\n"
            f"DB CANDIDATES (images labeled by item ID follow):\n"
        )},
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": mystery_b64}},
    ]

    for c in candidates:
        cid = c["id"]
        if cid not in candidate_images:
            continue
        desc = c.get("seller_description") or c.get("ai_description") or c.get("description") or ""
        content.append({"type": "text", "text": f"\n[DB Item #{cid} — {desc[:120]}]"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": candidate_images[cid]}})

    content.append({"type": "text", "text": (
        "\nDoes the mystery item (first image) appear to be the SAME PHYSICAL OBJECT as any of the DB items?\n"
        "Consider: same type, same color, same style, same distinguishing marks. Ignore lighting/angle differences.\n"
        "A match means this mystery item is likely a seller's consigned item that just wasn't tagged properly.\n\n"
        "Respond ONLY with a JSON array. Include only items that are a possible or likely match. "
        "If nothing matches, return []. No markdown, no explanation outside the JSON.\n"
        "Format:\n"
        '[{"item_id": 123, "confidence": "high", "reason": "same white IKEA dresser, identical handle notches"}]'
    )})

    resp = client.messages.create(
        model=MODEL,
        max_tokens=600,
        messages=[{"role": "user", "content": content}]
    )

    text = resp.content[0].text.strip()
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
        return []
    except json.JSONDecodeError:
        print(f"    ⚠ Could not parse model response: {text[:200]}")
        return []

# ── Category filtering ────────────────────────────────────────────────────────

CATEGORY_MAP = {
    "furniture":  ["furniture", "couch", "sofa", "chair", "desk", "dresser", "table",
                   "bed", "bookshelf", "shelf", "ottoman", "futon", "rug", "headboard"],
    "appliance":  ["appliance", "fridge", "microwave", "fan", "heater", "ac", "vacuum",
                   "washer", "dryer", "coffee maker", "toaster", "kettle"],
    "electronics":["electronics", "tv", "monitor", "speaker", "laptop", "computer",
                   "printer", "lamp", "light", "charger"],
    "decor":      ["decor", "decoration", "plant", "mirror", "art", "artwork", "frame",
                   "picture", "curtain", "pillow", "blanket"],
}

def filter_by_category(candidates: list[dict], mystery_category: str, mystery_type: str) -> list[dict]:
    """Return candidates most likely in the same category as the mystery item."""
    mc = mystery_category.lower()
    mt = mystery_type.lower()

    # Determine which keyword sets to match
    target_keywords = CATEGORY_MAP.get(mc, [])
    # Also try to match on item type words directly
    type_words = mt.split()

    def score(c: dict) -> int:
        cat = (c.get("category_name") or "").lower()
        desc = (c.get("description") or "").lower()
        combined = cat + " " + desc
        s = 0
        for kw in target_keywords:
            if kw in combined:
                s += 2
        for w in type_words:
            if len(w) > 3 and w in combined:
                s += 3
        return s

    scored = [(score(c), c) for c in candidates]
    # Include items with any relevance score; fall back to all if nothing scores
    relevant = [c for s, c in scored if s > 0]
    if not relevant:
        return candidates  # no filter match — compare against everything
    # Sort by score descending, cap at MAX_CANDIDATES_PER_CALL
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:MAX_CANDIDATES_PER_CALL]]

# ── Report generation ─────────────────────────────────────────────────────────

def build_report(results: list[dict]) -> str:
    """Generate a self-contained HTML report."""
    rows_html = ""
    for r in results:
        mystery = r["mystery"]
        matches = r["matches"]
        has_matches = bool(matches)

        # Mystery item panel
        mystery_img = f'<img src="data:image/jpeg;base64,{r["mystery_b64"]}" class="photo">'
        mystery_panel = f"""
        <div class="mystery-panel">
            {mystery_img}
            <div class="label">
                <span class="row-num">Row {mystery['row']}</span>
                <span class="item-desc">{mystery['description'] or '—'}</span>
                <div class="identified">
                    {mystery['info'].get('item_type','?')} &middot;
                    {mystery['info'].get('color','?')} &middot;
                    {mystery['info'].get('details','?')}
                </div>
            </div>
        </div>"""

        # Match panels
        if has_matches:
            match_cards = ""
            for m in matches:
                cid = m.get("item_id")
                conf = m.get("confidence", "?")
                reason = m.get("reason", "")
                b64 = r["candidate_b64s"].get(cid, "")
                img_tag = f'<img src="data:image/jpeg;base64,{b64}" class="photo">' if b64 else '<div class="no-photo">No photo</div>'
                conf_class = {"high": "conf-high", "medium": "conf-medium", "low": "conf-low"}.get(conf, "conf-low")
                cand = r["candidate_meta"].get(cid, {})
                desc = cand.get("seller_description") or cand.get("ai_description") or cand.get("description") or "—"
                match_cards += f"""
                <div class="match-card">
                    {img_tag}
                    <div class="match-info">
                        <span class="item-id">Item #{cid}</span>
                        <span class="conf-badge {conf_class}">{conf}</span>
                        <div class="match-desc">{desc[:150]}</div>
                        <div class="reason">"{reason}"</div>
                    </div>
                </div>"""
            matches_html = f'<div class="matches">{match_cards}</div>'
            row_class = "result-row has-matches"
        else:
            matches_html = '<div class="no-matches">✓ No matches found — likely safe to claim as Campus Swap inventory</div>'
            row_class = "result-row no-match"

        rows_html += f"""
        <div class="{row_class}">
            <div class="row-inner">
                {mystery_panel}
                <div class="arrow">→</div>
                {matches_html}
            </div>
        </div>"""

    flagged_count = sum(1 for r in results if r["matches"])
    total = len(results)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Campus Swap — Mystery Item Verification</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #f5f4f0; color: #1a1a1a; padding: 24px; }}
  header {{ max-width: 1100px; margin: 0 auto 24px; }}
  h1 {{ font-size: 22px; font-weight: 700; margin-bottom: 6px; }}
  .summary {{ font-size: 14px; color: #555; }}
  .summary strong {{ color: #c0392b; }}
  .result-row {{ max-width: 1100px; margin: 0 auto 16px;
                 background: #fff; border-radius: 10px; overflow: hidden;
                 border: 2px solid #e8e6e0; }}
  .result-row.has-matches {{ border-color: #e8a838; }}
  .row-inner {{ display: flex; align-items: flex-start; gap: 0; }}
  .mystery-panel {{ width: 260px; flex-shrink: 0; padding: 16px;
                    background: #fafaf8; border-right: 1px solid #e8e6e0; }}
  .photo {{ width: 100%; height: 180px; object-fit: cover;
            border-radius: 6px; display: block; margin-bottom: 10px; }}
  .no-photo {{ width: 100%; height: 180px; background: #eee; border-radius: 6px;
               display: flex; align-items: center; justify-content: center;
               font-size: 12px; color: #999; }}
  .label {{ font-size: 13px; }}
  .row-num {{ font-weight: 700; font-size: 15px; display: block; margin-bottom: 3px; }}
  .item-desc {{ color: #444; display: block; margin-bottom: 6px; }}
  .identified {{ font-size: 11px; color: #888; line-height: 1.5; }}
  .arrow {{ font-size: 24px; color: #bbb; padding: 0 12px;
            align-self: center; flex-shrink: 0; }}
  .matches {{ flex: 1; padding: 16px; display: flex; flex-wrap: wrap; gap: 12px; }}
  .match-card {{ width: 200px; border: 1px solid #e0ddd5; border-radius: 8px;
                 overflow: hidden; background: #fafaf8; }}
  .match-info {{ padding: 8px; font-size: 12px; }}
  .item-id {{ font-weight: 700; font-size: 13px; margin-right: 6px; }}
  .conf-badge {{ display: inline-block; padding: 1px 7px; border-radius: 20px;
                 font-size: 11px; font-weight: 600; }}
  .conf-high   {{ background: #fde8e8; color: #c0392b; }}
  .conf-medium {{ background: #fef3cd; color: #856404; }}
  .conf-low    {{ background: #e8f4f8; color: #2471a3; }}
  .match-desc  {{ margin-top: 5px; color: #555; line-height: 1.4; }}
  .reason      {{ margin-top: 5px; color: #777; font-style: italic; }}
  .no-matches  {{ flex: 1; padding: 16px; align-self: center;
                  font-size: 13px; color: #2e7d32; }}
  .no-match    {{ border-color: #c8e6c9; }}
</style>
</head>
<body>
<header>
  <h1>Campus Swap — Mystery Item Verification Report</h1>
  <p class="summary">
    {total} mystery items scanned &nbsp;·&nbsp;
    <strong>{flagged_count} flagged for review</strong> &nbsp;·&nbsp;
    {total - flagged_count} clear
  </p>
</header>
{rows_html}
</body>
</html>"""

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    validate_setup()

    # Scan mystery_items/ folder for photos, sorted numerically by filename
    PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
    photo_files = sorted(
        [p for p in MYSTERY_PHOTOS_DIR.iterdir() if p.suffix.lower() in PHOTO_EXTENSIONS],
        key=lambda p: int(re.sub(r"\D", "", p.stem) or 0)
    )

    if not photo_files:
        sys.exit(f"No photos found in {MYSTERY_PHOTOS_DIR}/")

    # Build mystery_items list from filenames alone (no CSV needed)
    mystery_items = [{"row": p.stem, "description": "", "path": p} for p in photo_files]

    print(f"Found {len(mystery_items)} photos in {MYSTERY_PHOTOS_DIR}/")

    if MAX_ITEMS is not None:
        mystery_items = mystery_items[:MAX_ITEMS]
        print(f"Limiting to first {MAX_ITEMS} items (MAX_ITEMS is set)\n")

    # Connect to DB and fetch candidates
    db_conn = connect_db()
    candidates = get_candidates(db_conn)
    db_conn.close()
    print(f"Found {len(candidates)} unassigned DB candidates\n")

    if not candidates:
        sys.exit("No unassigned DB items found. Nothing to compare against.")

    # Set up S3 client
    s3 = boto3.client(
        "s3",
        region_name=AWS_REGION,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )

    # Pre-fetch all candidate images from S3
    print("Fetching candidate photos from S3...")
    candidate_images = {}  # item_id → b64 string
    candidate_meta   = {}  # item_id → dict
    for i, c in enumerate(candidates):
        cid = c["id"]
        candidate_meta[cid] = c
        photo_key = (c["photo_url"] or "").strip()
        if not photo_key:
            print(f"  ⚠ Item #{cid} has blank photo_url, skipping")
            continue
        img = fetch_s3_image(s3, f"uploads/{photo_key}")
        if img:
            candidate_images[cid] = image_to_b64(img)
        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{len(candidates)} fetched...")
    print(f"  ✓ {len(candidate_images)} photos loaded ({len(candidates)-len(candidate_images)} missing/skipped)\n")

    # Set up Anthropic client
    ai = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    results = []

    for idx, mystery in enumerate(mystery_items):
        row_num = mystery["row"]
        desc    = mystery["description"]
        print(f"[{idx+1}/{len(mystery_items)}] Row {row_num}: {desc or '(no description)'}")

        # Use the path already found during folder scan
        photo_path = mystery["path"]

        mystery_bytes = load_local_image(photo_path)
        if not mystery_bytes:
            print(f"  ⚠ Could not load photo — skipping")
            continue

        mystery_b64 = image_to_b64(mystery_bytes)

        # Pass 1: identify
        print(f"  → Identifying item...")
        info = identify_mystery_item(ai, mystery_b64, desc)
        print(f"     {info.get('item_type','?')} / {info.get('category','?')} / {info.get('color','?')}")
        time.sleep(0.3)  # small rate-limit buffer

        # Filter candidates by category
        filtered = filter_by_category(list(candidates), info.get("category",""), info.get("item_type",""))
        # Only use candidates that have photos
        filtered_with_photos = [c for c in filtered if c["id"] in candidate_images]
        print(f"  → Comparing against {len(filtered_with_photos)} category-filtered candidates...")

        # Pass 2: compare (batch if needed)
        all_matches = []
        for batch_start in range(0, len(filtered_with_photos), MAX_CANDIDATES_PER_CALL):
            batch = filtered_with_photos[batch_start:batch_start + MAX_CANDIDATES_PER_CALL]
            batch_images = {c["id"]: candidate_images[c["id"]] for c in batch}
            matches = compare_against_candidates(ai, mystery_b64, info, batch, batch_images)
            all_matches.extend(matches)
            time.sleep(0.3)

        if all_matches:
            print(f"  ⚠ {len(all_matches)} potential match(es) flagged!")
        else:
            print(f"  ✓ No matches")

        results.append({
            "mystery": {**mystery, "info": info},
            "mystery_b64": mystery_b64,
            "matches": all_matches,
            "candidate_b64s": {c["id"]: candidate_images[c["id"]] for c in filtered_with_photos if c["id"] in candidate_images},
            "candidate_meta": {c["id"]: c for c in filtered_with_photos},
        })

    # Generate report
    print(f"\nGenerating report → {REPORT_OUTPUT}")
    html = build_report(results)
    REPORT_OUTPUT.write_text(html, encoding="utf-8")

    flagged = sum(1 for r in results if r["matches"])
    print(f"\n{'='*50}")
    print(f"Done. {flagged}/{len(results)} items flagged for review.")
    print(f"Open report.html in your browser.")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
