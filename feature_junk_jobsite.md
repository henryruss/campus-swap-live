# Junk Removal — Slice 3: The Job Site

**Status:** 🔲 Not started. Next build (the crew list shipped 2026-11-21).
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
3. **Truck:** **Returned it** · **Handed off** (going on to the next job), each a single tap. Henry dropped "Still have it" and dropped picking a person on 2026-11-22. Ideas for closing the loop later: Ramp card checkouts, a regular drop spot for midday crews, an automatic return notice. None of these are built.
4. **Payment:** see below.

**At the top of the job, in big type:** **Paid ✓**, or **"Not paid: collect before you leave"** plus a **Show pay code** button. Once the crew leave the property, the business owns the stuff and the customer could flake. If the customer isn't home and hasn't paid, the crew wait.

## Payment: three ways, card preferred
| How | When | Amount |
|---|---|---|
| Pay link | Ahead of time; the manager sends it at booking | Quote minus a prepay discount (`AppSetting`, default 5%) |
| QR code | On site, from the crew phone | Quote |
| Cash | On site, recorded by crew ("Cash: $___", filled in with the quote) | Quote |

- **QR code (checked 2026-11-21):**
  - The QR code is easy from a website. The customer scans it with their phone camera, which opens a Stripe payment page where they pay with Apple Pay, Google Pay or a card typed in.
  - **A card tapped on the crew phone** ("Tap to Pay on iPhone") is not possible from a website. It needs a native app built with Stripe Terminal.
  - **A middle option:** a Stripe smart card reader (WisePOS E / S700). The website can send a charge to it over the internet, and the customer taps their card on the reader. It costs hardware and needs Wi-Fi, such as a phone hotspot.
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

## Decided (Henry, 2026-11-21)
- **Until Stripe is wired up, Payment stays open.** No "Paid by card" stand-in, so a job can't auto-close until 3b. Build 3b right after 3a, or together with it.
- **The manager's Mark done stays,** as an override for a job with no checklist.
- **No "before" photos for now.** Quoting will collect them when it's built.
- **Order: 3a checklist → 3b Stripe → claim pool later.** There are no employees yet. Design the job stages with the pool in mind (Open → Claimed → In progress → Done → Settled, all derived, never stored).
- **Shape:**
  - **Crew:** the checklist is on the job card (Today and Not finished cards only). Payment goes at the top of the card, and a small "2 of 4" sits in the head.
  - **Manager:** the job window gets a Checklist section (photos, who and when, move, reopen, cash received). Calendar cards get one small progress mark. A "Needs attention" list goes on the desktop side.

## Decided (Henry, 2026-11-22): the My jobs layout
- **Every job is a row you tap open.** Today's jobs are open; Not finished yet, Coming up and Waiting on review are closed.
- **When a checklist is complete,** the job folds up and says "Job done · waiting on manager review", and it moves to **Waiting on review**. Crew can still open it and change things until a manager marks it done. After that it's read-only for crew; managers can still change it.
- **Finished jobs:**
  - On a phone, the "jobs done" total opens the Finished page.
  - On a wide screen, a **Finished** list sits in the right column, newest first.
  - Every finished row opens that job.
- **Photos:**
  - A photo opens in a viewer on the same page: arrows and arrow keys on a computer, swipe on a phone, neither when there's only one.
  - Add buttons are big enough for a thumb.
- **Addresses:** a typed address that wasn't picked from suggestions gets no map, just "Address not confirmed", instead of Google's guess or error box.
- **Closing a row** near the bottom of the page doesn't jump the page.
- **Next:**
  - Desktop photo upload by QR code, so a computer can hand off to a phone camera.
  - Then the manager side.
- **Later:** a quote-photos square beside the map that opens a carousel (reuse the viewer) when quoting is built.

## Solved: a second tap on iPhone (2026-11-22)
**What happened:**
1. Tap a photo square; the iPhone photo menu opens.
2. Dismiss the menu by tapping the page.
3. The next tap on a photo square did nothing; the tap after that worked.

**The cause** (found with a temporary tap log sent to the dev server):
- iOS takes about 0.2–0.8s to finish closing the menu after the dismissing tap, and silently ignores any request to open a menu until then.
- A quick next tap always landed inside that window.

**The fix (`crew.js` `pickPhotos`):**
- Each tap makes a fresh file input.
- If the last menu hasn't reported closing yet (its `cancel` or `change` event), the new one waits for it (up to 900ms) and then opens. Safari still counts a request that soon after a tap as coming from the tap.
- The square shows an "opening" pulse during the wait, so the ⅓-second delay reads as intended.

## Open questions
- **Photo storage:** reuse the legacy upload path (`/var/data` on Render), with limits on size and count.
- **Refunds:** a prepaid job that's cancelled.

## Later
Quote photos shown to crew; crew claiming open jobs; settling cash and pay; several trucks a day.
