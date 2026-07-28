# Spec: Year 1 Investor Board Report — Data Pull

## Goal
Produce the underlying data (as structured JSON/CSV, one file per section) for a board-meeting
report covering Campus Swap's first operational season. This is a **one-time historical pull**,
not a recurring feature — no new admin routes, no new models, no schema changes. Output feeds
into a later PDF layout pass (not part of this spec).

**No items have sold yet this season.** Do not build or report any sold/unsold, sell-through
rate, or revenue metrics. Do not build a delivery-logistics section — `DeliveryStop`/`DeliveryRun`
only populate after a sale, so there is nothing to report there. Storage **cost** is out of scope
(covered in a separate financial document) — only report storage *utilization*.

## Scope & Constraints
- **Read-only.** This should be a standalone script (e.g. `scripts/board_report_pull.py` run via
  `flask shell` context or a one-off management command), not new `app.py` routes.
- **No model or migration changes.** Everything needed already exists on `InventoryItem`, `User`,
  `StorageLocation`, `IntakeRecord`, `Shift`, `ShiftPickup`, `ShiftAssignment`.
- **Date range: all data to date** (this is a full Year 1 wrap-up, not a sliced time window).
  Exclude anything tied to `is_internal_account=True` or `is_tutorial_user=True` accounts/items —
  those are seeded/QC/tutorial data, not real seller activity.
- **Output:** write one JSON file per section below to `/tmp/board_report/` (or similar scratch
  location), plus print a plain-text summary table to stdout for a quick sanity check before
  handoff to the PDF pass.

## Section 1 — Season at a Glance
Headline counts for the top of the report. Because "how many items" has several legitimate
answers depending on which funnel stage you mean (see Section 2), pull the Stage C (in storage)
number here as the headline, and be explicit in the label that it's "items currently in storage,"
not "items listed" or "items live in shop" — those get their own numbers in Section 2.
- Items currently in storage (Stage C from Section 2)
- Total unique sellers: `count(distinct InventoryItem.seller_id)` where `date_added IS NOT NULL`,
  excluding internal/tutorial accounts
- Date range covered: `min(arrived_at_store_at)` to `max(arrived_at_store_at)`
- Frame this section's narrative as "inventory built and ready to sell" — not as a sales result.

## Section 2 — Item Funnel (Listed → Picked Up → Storage → Rephotographed → Live in Shop)
This is the core narrative section — Year 1 saw real attrition and additions at every stage, and
the board should see the funnel explicitly rather than a single flat "inventory" number. Report
each stage as its own count, plus the deltas between stages, so the shrinkage/growth at each step
is visible and explainable rather than looking like unexplained loss.

**Stage A — Items listed.** Every `InventoryItem` created by a real seller
(`date_added IS NOT NULL`), regardless of what happened afterward. This is the top of the funnel.

**Stage B — Items actually picked up.** Subset of Stage A where `picked_up_at IS NOT NULL`.
Report the count AND the count of listed-but-never-picked-up items (no-shows, cancellations,
missed stops) as its own line — that gap is a legitimate, explainable operational number, not
noise to hide.

**Stage B+ — Extra items collected beyond the original listing.** Items received during pickup
that were never part of a seller's original submission.
- **Verify against `models.py` before writing this query** — do not assume. Two candidate
  mechanisms exist in the codebase and the correct one (possibly both) needs confirming:
  1. Quick Capture flow — `InventoryItem.is_quick_capture = True` (mover photographs a
     found/donated/spot-consigned item in the field and it's created directly as inventory)
  2. Intake "unknown item" flow — `IntakeFlag.flag_type = 'unknown'` records logged by an
     organizer at the warehouse, which may or may not later resolve into a real `InventoryItem`
  Report extra items as their own additive line to Stage B, not folded silently into it.

**Stage C — Items received into storage.** `arrived_at_store_at IS NOT NULL` AND
`storage_location_id IS NOT NULL` — this is Stage B (+ extras) minus anything that was picked up
but never successfully logged into a storage location.

**Stage C minus — Items deemed unsellable.** `status = 'rejected'`, but split into two sub-counts
since they represent different failure points:
  - Rejected before ever being picked up (bad photos/valuation call — `picked_up_at IS NULL`)
  - Rejected after arriving in storage (damaged/missing/QC call made once physically received —
    `arrived_at_store_at IS NOT NULL`). Cross-reference `IntakeFlag` (`flag_type IN ('damaged',
    'missing')`) where available to show *why*, not just that it was rejected.

**Stage D — Rephotographed.** Per the warehouse re-photography campaign — verify the exact
field/logic against `models.py` and `AppSetting` before writing this query; do not assume
`needs_new_photo == False` is equivalent to "has been rephotographed under the campaign" without
checking. The correct signal is most likely tied to `ItemPhoto.captured_at` on/after the
re-photography campaign's start date (stored as an `AppSetting`), not just a proxy flag that may
be False for other reasons (e.g. an item that never needed rephotographing in the first place).

**Stage E — Live in shop (buyer-visible).** Full existing shop-visibility filter:
`ai_approved == True`, `needs_new_photo == False`, `status != 'rejected'`, `price > 0`,
`storage_location_id IS NOT NULL`. This is the bottom of the funnel and should be the smallest
number — a direct visual of "here's what actually made it all the way through."

**Output for this section:** one row per stage with a running count and the net change vs. the
prior stage (labeled additions/losses separately, not just a net delta), plus a one-line plain-
English caption per stage transition (e.g. "212 items picked up; 34 additional items found
on-site and added" / "18 items rejected after arrival due to damage").

## Section 2b — Inventory Composition by Category
Same grouping as before, but now scoped explicitly to **Stage C (in storage)** as the base
population, with a note in the output that this predates the rephotography/shop-eligibility
filtering applied in Section 2 Stage D/E.
- Group `InventoryItem` by `category_id` (join `Category` for display name)
- Per category: total count, count by `status` (`pending_valuation`, `needs_info`, `approved`,
  `available`, `rejected`)
- Grand total row across all categories

## Section 3 — Where Items Came From
- Join `InventoryItem.seller_id` → `User.pickup_location_type`
- Group into three buckets: `on_campus`, `off_campus_complex`, `off_campus_other`
- Report both item count and % of total per bucket
- Note in output metadata: this reflects the seller's registered pickup location type, not a
  per-item verification of dwelling type — call this out as a footnote in the final report copy.

## Section 4 — Pricing by Category
- Per category: average `suggested_price`, average `price` (current listed price), and the % diff
  between them (listed vs. suggested)
- No sold-price comparison — nothing has sold. Label this clearly as "suggested vs. listed," not
  "discount," since no markdown history table exists (`price_updated_at` only tracks the most
  recent change, not a full history).

## Section 5 — Storage Utilization
- Per `StorageLocation`: `name`, item count (`count(InventoryItem)` where
  `storage_location_id = this location` and status not `rejected`), `is_full`, `capacity_note`
- Grand total items stored across all locations
- **Do not include cost** — that lives in the financial breakdown doc.

## Section 6 — Pickup Logistics
- Per week (or per `Shift.date` if weekly grouping isn't natural): number of distinct trucks used
  (`count(distinct ShiftPickup.truck_number)` or equivalent per-shift truck field — verify exact
  field name in `Shift`/`ShiftPickup` before writing the query), number of pickup stops completed
  (`ShiftPickup` where a completion timestamp is set), number of items picked up that week
  (`InventoryItem.picked_up_at` within that week's range)
- Grand totals: total trucks-shifts run, total pickups completed, total items picked up

## Section 7 — Crew Work Coverage
- Per worker (or summarized as a total, whichever reads better for a board audience — recommend
  **summarized total**, not a per-worker grid): total shifts worked, broken out by
  `ShiftAssignment.role_on_shift` (mover vs. organizer)
- Total distinct crew members who worked at least one shift
- Do not include a literal date/time schedule grid — that's an internal ops artifact, not
  board-relevant detail. A one-line "X crew members covered Y total shifts across Z weeks" is
  the right altitude.

## Business Logic / Validation Notes
- Filter out `is_internal_account=True` and `is_tutorial_user=True` throughout — these are
  seeded/QC/demo data, not real seller or crew activity, and would distort every count.
- If a section's underlying data is empty or a query returns zero rows, output the section with
  explicit `"count": 0` rather than omitting it — the PDF pass needs to know a section legitimately
  had no data vs. the query failing silently.
- Verify exact field names for truck count on `Shift`/`ShiftPickup` against the current schema
  before writing Section 6 — do not assume without checking `models.py`.

## Testing Checklist
- [ ] Section 2 funnel is monotonically consistent: Stage A ≥ Stage B; Stage B + extras = Stage C
      + (picked-up-but-not-stored, if any); Stage C − unsellable ≥ Stage D ≥ Stage E
- [ ] The two "extra items" mechanisms (quick capture vs. resolved unknown-item flags) were both
      checked against the current schema, and the spec was followed for whichever actually applies
- [ ] Section 2b's total items (Stage C population) matches Section 2's Stage C count exactly
- [ ] Section 4's three location-type buckets sum to the same total as Section 2 Stage A (or
      Stage C, whichever population pricing/location is scoped to — confirm consistent scoping)
- [ ] Section 5's grand total item count is consistent with Section 2b (minus rejected)
- [ ] Internal/tutorial accounts confirmed excluded from every section (spot-check a known
      tutorial seller/worker and confirm they don't appear in counts)
- [ ] All output files written successfully with non-null values for every field, including
      explicit `0` counts where a stage or sub-bucket is legitimately empty
