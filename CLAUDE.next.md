# Campus Swap — Claude Instructions (v2, DRAFT)

> Draft replacement for CLAUDE.md. Built section by section. Do not treat as active until it replaces CLAUDE.md.

---

## 1. Mission & Positioning

### The situation
Campus Swap ran a free consignment move-out service at UNC in Spring 2026. It served hundreds of students and brought in a few thousand dollars in revenue, but it lost tens of thousands. Investors are unhappy. **Spring 2027 is the last chance.** Treat the existing site like a business we just acquired: keep the infrastructure that works, and rebuild the product and pitch around making money.

### The pivot
**We are a paid move-out service, not a free marketplace.** Customers pay up front. Item resale is upside, not the business model.

| Spring 2027 (UNC only) | Status |
|---|---|
| **Junk removal**: the main revenue line | New |
| **Consignment**: now paid, no more free pickups | Changed |
| **Shop**: resale to move-in buyers | Kept, secondary |
| **Housing partnerships**: UNC Housing, apartment complexes, landlords | New, terms undefined per partner |
| Storage | **Out of scope.** Do not build or market it. |

### Who pays
1. **Students moving out** (and likely their parents)
2. **Housing partners**. The model varies by partner and is not yet defined: promotion only, paid post-move-out cleanouts, or co-promotion of the shop at move-in.
3. **Move-in buyers**, through the shop

### Our edge
Junk haulers charge hundreds and throw everything away. Consignment-only services make you do the work and pay you later, maybe. **We clear the whole room, and the stuff worth selling pays you back.**

### Service model (working draft, subject to change)
- **The student declares:** how many items are junk and how many are for consignment.
- **Campus Swap decides** whether a consignment item is actually worth selling. (A trash can gets junked. A nice couch gets sold.) The exact flow for this still needs to be designed.
- **Junk removal pricing is per truckload, against a published rubric.** Placeholder rates: first load $100, each additional load $50.
  - The site gives an estimate from the declared item counts.
  - The driver photographs every truckload, and the photos back up the final receipt.
  - If the student underestimates and it takes more loads, they pay for the extra loads.
- **Consignment pricing is a flat fee per item.** Placeholder rate: $20 per item.
  - Consignment items are collected on a separate trip, or at least kept out of the junk truckloads.
  - The seller payout when an item sells is separate from the service fee.
- **Payment:** the card is saved at booking and charged after the job, once the receipt is final.

### Open questions (do not assume answers)
- Does consignment value ever offset the junk removal fee?
- If we reject a consignment item, does it get junked? Is its $20 refunded or converted to junk pricing?
- What are the final truckload rubric and rates? How do we define a "truckload"?
- What are the terms of each housing partnership?

### Rules for Claude
- **Rank features by time-to-cash.** Upfront service revenue comes before item-sale revenue.
- **Junk removal is first-class.** Never treat it as a sub-feature of consignment.
- **Pricing is config, not code.** Rates, rubric tiers and per-item fees live in AppSettings. They will change.
- **UNC only this spring, with zero UNC hardcoding.** Every school is the long-term goal.
- **Use real stats only.** Never invent numbers. Source them from `financials-summary.md` (TODO: Henry to create).
- **Henry owns the prose.** Claude owns structure: blocks, layout, what goes where. Use placeholder copy and don't polish wording.
- **Don't build storage.**

---

## 2. Design System — TODO
## 3. Information Architecture — TODO
## 4. Engineering Rules — TODO
## 5. Canonical Docs — TODO
## 6. Build Calendar — TODO
