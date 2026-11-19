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

### Step 3: Assigning in the job modal
- New `JobAssignment` table (`junk_job_assignment`): `job_id`, `user_id`, `created_at`, `created_by_id`, unique on `(job_id, user_id)`.
- **The job modal gets a Crew field:** pick any number of people from the team. It defaults to nobody, and there's a one-tap "Add me".
- **Calendar cards show the assignees' initials.**
- **History:** assignment changes go into `JobEvent` as `crew: [old names, new names]`.
- **Deleting a job** deletes its assignments too.

### Step 4: Crew portal
- `/junk/crew` lists my assigned jobs: upcoming first, then a short list of recent done jobs.
- Each job shows the name, phone (tap to text or call), address (tap for maps), quote, notes, and who else is on it.
- Crew can't edit anything yet.

**Answered 2026-11-18:**
- **More than 2 people on a job is rare.** The 40% labor cost of a 2-person job is the normal case.
- **A manager who works a job gets 20% too.** Pay goes to everyone assigned, whatever their role.
