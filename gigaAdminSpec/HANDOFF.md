# Campus Swap — Ops System Handoff State

> Update this file after every Claude Code session. It is the source of truth
> for what has actually been built, what changed from the spec, and what the
> next session needs to know. Paste the relevant sections into Claude Code at
> the start of each session alongside CODEBASE.md and OPS_SYSTEM.md.

---

## Current State

**Last updated:** [DATE]
**Active spec:** feature_worker_accounts (Spec #1)
**Overall status:** Not started — ready to begin

---

## Completed Specs

*None yet.*

---

## Spec #1 — Worker Accounts (In Progress)

**Status:** Not started
**Spec file:** `feature_worker_accounts.md`
**Started:** —
**Completed:** —

### What Was Built
*Fill in after Claude Code session.*

### Deviations from Spec
*Any places where implementation differed from the spec, and why.*

### New Fields / Tables Added
*Exact column names and types as implemented — use this if spec and code diverge.*

### Bugs Found During Sign-Off
*Any issues discovered during SPEC_CHECKLIST.md review.*

### Decisions Made During Implementation
*Anything that came up mid-build that required a choice.*

---

## Spec #2 — Shift Scheduling (Planned)

**Status:** Not started — spec not yet written
**Dependencies:** Spec #1 must be signed off first

---

## Spec #3 — Driver Shift View (Planned)

**Status:** Not started — spec not yet written
**Dependencies:** Spec #2 must be signed off first

---

## Spec #4 — Organizer Intake (Planned)

**Status:** Not started — spec not yet written
**Dependencies:** Spec #3 must be signed off first

---

## Spec #5 — Payout Reconciliation (Planned)

**Status:** Not started — spec not yet written
**Dependencies:** Spec #4 must be signed off first

---

## Spec #6 — Route Planning (Planned)

**Status:** Not started — spec not yet written
**Dependencies:** Spec #2 must be signed off first

---

## Spec #7 — Seller Progress Tracker (Planned)

**Status:** Not started — spec not yet written
**Dependencies:** Spec #4 must be signed off first

---

## Spec #8 — Seller Rescheduling (Planned)

**Status:** Not started — spec not yet written
**Dependencies:** Spec #6 must be signed off first

---

## Spec #9 — SMS Notifications (Planned)

**Status:** Not started — spec not yet written
**Dependencies:** Specs #6 and #8 must be signed off first

---

## Known Issues / Tech Debt

*Running list of things that need fixing that aren't blocking current work.*

---

## Environment Notes

*Any Render config changes, new environment variables added, or deployment
gotchas discovered during implementation.*

| Variable | Purpose | Added in Spec |
|----------|---------|---------------|
| *(none yet)* | | |

---

## How to Start a Claude Code Session

1. Open Claude Code (Sonnet, standard mode — use extended thinking only for
   the optimizer in Spec #2)
2. Paste these files in order:
   - `CODEBASE.md` (existing codebase reference)
   - `OPS_SYSTEM.md` (ops platform master reference)
   - `HANDOFF.md` (this file — current build state)
   - The active spec file (e.g. `feature_worker_accounts.md`)
3. Tell Claude Code: "Read all four files before writing any code. Start with
   CODEBASE.md to understand the existing patterns, then implement the spec.
   Ask me before making any decision not covered by the spec."
4. After the session, update this file with what was built and any deviations.
