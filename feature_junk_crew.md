# Junk Removal — Slice 2: Crew

**Status:** 🟡 In progress. Steps 1–2 are built, steps 3–4 aren't yet.
**Depends on:** Slice 1, the manager calendar (feature_junk_calendar.md)

---

## Goal

A manager can put people on a job, and those people can see their jobs.

## Decisions (Henry, 2026-11-18)
- **Managers assign.** Crew can't claim jobs yet. Later, crew may go "on call" and claim open jobs, so nothing here should block that.
- **Managers can work jobs.** Anyone with junk access can be assigned, crew or manager. A manager may quote a small job and do it on the spot: assigning yourself, then marking the job done in one sitting, must stay easy.
- **Crew size varies.** Usually 2, sometimes 1, more on big jobs. There are no fixed slots and no minimum.
- **Crew pay is 20% of the job total per person assigned.** It's config (`AppSetting junk_crew_pay_pct`, default 20), not code. Pay itself is out of scope here.

## Steps (one at a time, each reviewed with screenshots)

### Step 1: Crew role and dev switch ✅
- `User.is_junk_crew` (migration `d5a91e7c3b20`).
- `/junk/crew` is the crew home, empty for now.
- `junk_home()` lands managers on the calendar and crew on `/junk/crew`.
- Crew-only accounts are confined to `/junk`, like manager-only accounts.
- The dev-only pill (bottom-left) switches between the dev manager and dev crew accounts. It's on only when the server is in debug mode and neither `RENDER` nor `TESTING` is set.
- Tests: `test_junk_crew.py`

### Step 2: Team page ✅
- A **Team** tab for managers at `/junk/manage/team`. It lists everyone with junk access: name, email, phone, and the role (Manager or Crew).
- **Add crew:** a manager enters an email, plus an optional name and phone.
  - If an account with that email exists, it gets `is_junk_crew`.
  - Otherwise a new account is created with no password.
  - No email is sent. The person signs in with Google or uses "Forgot or never set a password?".
- **Remove from crew** clears `is_junk_crew`. It never deletes the account.
- **Managers are listed but read-only.** Manager accounts are still created by hand.
- **The add form hides behind a `+ Crew` button**, the same pattern as `+ Job`. It reopens after a validation error (`?add=1`).
- **Phone numbers display as (919) 555-0142** (`jr_phone` filter); they're stored as typed.
- **On mobile,** email and phone sit on separate lines, so the phone never gets cut off.
- **Out of scope:** invite links, and moving returning legacy workers over in bulk.

### Step 3: Assigning crew (Henry, 2026-11-18: "the same feel as Unscheduled jobs")
Crew are chips you drag onto jobs. Dragging onto a job, dragging off it, and adding or removing inside the job modal all work.

**3a — data, modal, cards** ✅ (built, not yet committed)
- **New table** `JobAssignment` (`junk_job_assignment`, migration `e7b4c2a9d1f3`): `job_id`, `user_id`, `created_at` and `created_by_id`, unique on `(job_id, user_id)`. Assignments are deleted along with their job.
- **Anyone with junk access can be assigned,** crew or manager. `set_crew(job, person, actor, on)` lives in `junk/jobs.py`.
- **One endpoint:** `POST /manage/job/<id>/crew` with JSON `{user_id, action: add|remove}`. Managers only. It answers with the re-rendered `_job_crew.html`.
- **Modal Crew row:** chips with × to remove, `+ Me`, and a `+ Add…` picker for anyone else on the team. New jobs get crew once they exist. Crew controls never trigger an autosave.
- **Cards (desktop):** crew get their own row of name pills (Henry, 2026-11-18), with the people loaded in one query per calendar.
  - **Pills per row depend on the card's own width:** two per row on a wide card, one per row on a narrow one such as a laptop week column. That way a full name fits on one line.
  - **Long names:** a long first name ends in "…"; a long last name hyphenates, up to 2 lines.
- **Cards (phone):** initials bubbles on their own row. Month chips show no crew. Initials use letters only, so "Manager (dev)" becomes MD.
- **Modal crew row order:** `[+ Add…] [+ Me]` and then the people, so the buttons never move.
- **History:** changes are recorded as `crew: [before names, after names]` and merge into the 10-minute edit burst; adding someone and then removing them leaves no entry.

**3b — crew panel + drag** (next)
- **Where the list sits:** on the right on desktop, mirroring Unscheduled, and at the bottom on phone. It shows everyone on the Team page, crew first.
- **Assign:** drag a person onto a job card.
- **Unassign or move:** on desktop, drag a name pill off a card back to the list, or onto another job. Phones don't drag crew off cards (Henry).

### Step 4: Crew portal
- `/junk/crew` lists my assigned jobs: upcoming first, then a short list of recent done jobs.
- Each job shows the name, phone (tap to text or call), address (tap for maps), quote, notes, and who else is on it.
- Crew can't edit anything yet.

**Answered 2026-11-18:**
- **More than 2 people on a job is rare.** The 40% labor cost of a 2-person job is the normal case.
- **A manager who works a job gets 20% too.** Pay goes to everyone assigned, whatever their role.
