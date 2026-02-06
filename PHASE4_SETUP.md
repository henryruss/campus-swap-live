# Phase 4 Admin Improvements Setup Guide

Phase 4 admin enhancements are complete. Here's what was added and how to use it.

---

## What Was Implemented

### 1. Payout Tracking
- **`sold_at`** timestamp — Records when an item was marked sold (via webhook or admin).
- **`payout_sent`** boolean — Tracks whether the seller has been paid their 40% payout.

### 2. Admin Panel Enhancements
- **Payout Status Column** — Shows "Pending" (yellow) or "Paid" (green) for sold items.
- **Payout Amount Display** — Shows the 40% amount due for pending payouts.
- **Mark Payout Sent** — Button to mark a payout as completed (prevents double-payment).
- **Sold Date** — Shows when each item was sold under the status badge.

### 3. Automatic Tracking
- When an item sells via Stripe webhook → `sold_at` is set automatically.
- When admin marks item as "Sold" → `sold_at` is set automatically.
- Both actions send the seller an email with payout details (40% amount).

---

## Database Migration Required

You need to add the new fields to your database:

```bash
FLASK_APP=app flask db migrate -m "Add payout tracking fields"
FLASK_APP=app flask db upgrade
```

**On Render:** The migration will run automatically if you have `flask db upgrade` in your release command.

---

## How to Use

### Marking an Item as Sold
1. In Admin Panel → Gallery Items table.
2. Click **"Sold"** button next to an available item.
3. System automatically:
   - Sets `sold_at` timestamp
   - Sends email to seller with 40% payout details
   - Updates stock count

### Marking Payout as Sent
1. Find a sold item with "Pending" payout status.
2. Click **"Mark Paid"** button.
3. System marks `payout_sent = True` (prevents accidental double-payment).

### Viewing Payout Status
- **Pending** (yellow badge) = Seller hasn't been paid yet
- **Paid** (green badge) = Payout completed
- Amount shown: `$XX.XX to pay` (40% of sale price)

---

## Quick Verification

1. **Mark an item as sold** → Check that `sold_at` appears in the table.
2. **Check payout status** → Should show "Pending" with payout amount.
3. **Mark payout sent** → Status changes to "Paid".
4. **Check seller email** → Should receive "Your Item Has Sold!" email with 40% details.

---

## Notes

- The "Mark Paid" button only appears for sold items with `payout_sent = False`.
- Once marked as paid, the button disappears to prevent accidental changes.
- You can still toggle items back to "Active" if needed (resets payout tracking).
