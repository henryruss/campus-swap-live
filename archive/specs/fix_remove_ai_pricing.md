# Fix Spec: Remove AI Auto-Pricing Feature (ItemAiResult)

## Goal

Fully remove the AI item pricing feature. It was never functional
(ANTHROPIC_API_KEY was never set in production), has left orphaned DB rows
with `item_id=NULL`, and is actively causing 500 errors on `POST /edit_item`
for real users. Remove all traces cleanly.

---

## Step 1: Shell Fix (Run Immediately — No Deploy Needed)

Before the code removal is deployed, clear the orphaned records that are
causing live 500 errors right now:

```python
# In Render shell → flask shell:
from models import db
result = db.session.execute(
    db.text("DELETE FROM item_ai_result WHERE item_id IS NULL")
)
db.session.commit()
print(f"Deleted {result.rowcount} orphaned rows")
```

This stops the bleeding immediately. The code removal below can then go
out in the next normal deploy.

---

## Step 2: Code Removal

### `models.py`

Delete the entire `ItemAiResult` model class. It will look something like:

```python
class ItemAiResult(db.Model):
    __tablename__ = 'item_ai_result'
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('inventory_item.id'), ...)
    status = db.Column(db.String, ...)
    # ... other fields
```

Also remove any backref on `InventoryItem` that references `ItemAiResult`,
e.g.:
```python
# Remove this if it exists on InventoryItem:
ai_result = db.relationship('ItemAiResult', backref='item', uselist=False)
```

### `app.py`

Search for and remove all of the following:

1. Any import or reference to `ItemAiResult`
2. Any route that reads or writes `item_ai_result` (e.g. an AI pricing
   trigger endpoint)
3. Any code in `edit_item`, `add_item`, or any other route that queries,
   creates, or updates `ItemAiResult`
4. Any helper function related to AI pricing (e.g. `_trigger_ai_pricing`,
   `_get_ai_price_suggestion`, or similar)
5. Any `ANTHROPIC_API_KEY` reference that exists solely for this feature
   (if it's used for other things, leave it)

Search terms to find all references:
- `ItemAiResult`
- `item_ai_result`
- `ai_result`
- `ai_price`
- `suggested_price` (check — if this field was only used by the AI feature,
  it can be removed too; if admin sets it manually, keep it)

### Templates

Search all templates for any AI pricing UI:
- Price suggestion banners
- "AI suggested price" displays
- Any loading spinners or status indicators tied to AI pricing

Remove those template blocks. If a template has an `{% if item.ai_result %}`
block, remove the entire conditional.

---

## Step 3: Migration

After removing the model, generate a migration to drop the table:

```bash
flask db migrate -m "remove_item_ai_result"
flask db upgrade
```

The migration should contain a single `op.drop_table('item_ai_result')`.

If Flask-Migrate doesn't auto-detect the removal (sometimes happens with
manual table drops), write it explicitly:

```python
def upgrade():
    op.drop_table('item_ai_result')

def downgrade():
    pass  # Not worth restoring
```

---

## Step 4: Verify

After deploy:
1. `POST /edit_item/<id>` — edit any item and save. Should succeed with
   no `IntegrityError` in logs.
2. Item deletion — should work cleanly.
3. `POST /add_item` — submit a new item. No AI-related errors in logs.
4. Check Render logs — `item_ai_result` should never appear again.

---

## Constraints

- `suggested_price` on `InventoryItem` — check whether admin uses this
  field manually in the approval flow. If yes, keep the DB field and any
  admin UI for it. Only remove it if it was exclusively populated by the
  AI feature.
- Do not remove the `ANTHROPIC_API_KEY` environment variable from Render
  settings — it may be used for other things (e.g. the API-powered
  artifacts feature). Only remove references to it inside the AI pricing
  code paths.
- No other models, routes, or templates should be touched beyond what
  directly references `ItemAiResult`.
