# Junk Removal — Slice 3: The Job Site

**Status:** 🔲 Not started. Waiting on Slice 2 step 4, the crew list.
**Depends on:** feature_junk_crew.md

---

## Goal
Henry isn't on site. A job proves itself from afar: **crew don't get paid unless the job is finished,** and a job is finished when its checklist is filled in.

**Phone first.** Crew are non-technical and fill this in on site, on a phone. Every step is one tap or one photo.

## Principles (Henry, 2026-11-19)
- **Get the information; don't block mistakes.** Every item is always open, on any job, in any order, on any date. If crew put job A's photos on job B, a manager moves them afterward.
- **No date gates.** A job scheduled for Sunday can be done on Saturday.
- **No Start button and no "On my way" text.** Crew call the customer themselves.
- **No Done button.** A job closes itself when all four items have an answer. Crew can still edit it, and managers can reopen it.
- **Expenses aren't tracked here.** Crew have Ramp cards for the rental truck and gas.

## The checklist (one per job)
Each answer records who gave it and when.

1. **Cleared out:** one or more photos of the empty space. This proves nothing was left behind; a dump receipt alone can't.
2. **Dump:** a photo of the receipt, or one tap: **"Dumped with another job"** (one receipt can cover several jobs).
3. **Truck:** **Returned it** · **Handed it to…** (pick a person) · **Still have it**. A handoff between crews is one crew's answer, and the manager sees the chain. For now this is one truck and a job or two a week; several trucks at once is out of scope.
4. **Payment:** see below.

**At the top of the job, in big type:** **Paid ✓**, or **"Not paid: collect before you leave"** plus a **Show pay code** button. Once the crew leave the property, the business owns the stuff and the customer could flake. If the customer isn't home and hasn't paid, the crew wait.

## Payment: three ways, card preferred
| How | When | Amount |
|---|---|---|
| Pay link | Ahead of time; the manager sends it at booking | Quote minus a prepay discount (`AppSetting`, default 5%) |
| QR code | On site, from the crew phone | Quote |
| Cash | On site, recorded by crew ("Cash: $___", filled in with the quote) | Quote |

- **Card payments are confirmed by Stripe's webhook only.** Crew can never mark a job paid by card.
- **The business absorbs card fees.**
- **Card is the default;** cash is offered smaller.
- **Cash:** crew record it, and a manager marks it **received** when they hand it over. Settling up (who keeps what) is handled outside the site for now.

## Manager side
- **Each job shows its checklist answers:** photos, who answered, and when.
- **Move a photo or answer to another job,** to fix mix-ups.
- **Reopen a closed job.**
- **Mark cash received.**

## Build order
- **3a — Checklist:** photos (cleared out, dump), the dump tap, truck answers, cash; auto-close and reopen; the manager's move tool.
- **3b — Stripe:** the pay link with the prepay discount, the QR code, the webhook, cash received.

## Decided (Henry, 2026-11-19)
- **Prepay discount starts at 5%,** and it's a setting.
- **"Handed it to…" picks from the team only,** using the same searchable team picker as the job modal's "+ Add…".

## Open questions
- **Photo storage:** reuse the legacy upload path (`/var/data` on Render), with limits on size and count.
- **Refunds:** a prepaid job that's cancelled.

## Later
Quote photos shown to crew; crew claiming open jobs; settling cash and pay; several trucks a day.
