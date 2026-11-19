# Junk Removal — Slice 1: Manager Calendar

**Status:** 🔲 Not yet built
**Depends on:** nothing (first junk removal build)
**Followed by:** Slice 2: Junk Crew (roles, migrating returning workers, invites, assigning crew to jobs)

---

## Goal

A manager can get a job from a phone call onto the calendar, put the day in order, and mark the job done.

The manager's homepage is `/junk/manage`: a week calendar plus a side list of jobs that don't have a date yet. All managers (Henry, Ben, Cam, David) have the same permissions. Nothing is ever hard-deleted.

**Design bar:** very little goes on the screen, and what's there has to feel finished. Don't add controls the flow below doesn't need.

---

## The real-world flow this models

1. **A customer calls David.** David can create the job right away with whatever he has (usually name, number and address), or he can wait.
2. **David goes out and quotes.** If the customer says yes, he enters the quote. Right now, quoting and the customer agreeing happen at the same time.
3. **The job gets a date.** It goes on the calendar, at the end of that day's line.
4. **The crew does the job,** and a manager marks it done.

If the customer says no, the job is archived. If they call back later, a manager restores it. Archiving is also how a job gets cancelled or deleted. **There's one way off the board, and it can always be undone.**

Jobs won't always follow these steps in order, so **every field is optional**. A job with no name shows as "Untitled job".

---

## Key Design Decisions

**A separate top-level folder.** Everything for junk removal lives in `junk/` at the repo root: its own Blueprint, routes, models, templates and static files. It's mounted at `/junk`. It reuses only infrastructure: `db`, `User`, Flask-Login, CSRF and `AppSetting`. Nothing in `junk/` imports from `app.py`, because `helpers.py` already has a circular import with it. Consignment code is legacy, so don't extend it and don't link to it.

**No status column. A job's state comes from its fields.**

| State | Rule | Where it shows |
|---|---|---|
| Archived | `archived_at` is set | Only on the Archived page |
| Done | `completed_at` is set | Its day, as a collapsed "✓ N done" line |
| Scheduled | `scheduled_date` is set | Its day, in queue order |
| Unscheduled | no date | The Unscheduled panel. Shows a "Needs quote" tag if there's no quote amount. |

The rules are checked top to bottom, and `Job.state` is a property that applies them. Because state is never stored separately, it can't disagree with the data. "Needs quote" isn't a separate status either; it just means the quote field is empty.

**Each day is a line, not a set of time slots.**
- There are no arrival times. Job #1 is first.
- **Done jobs leave the line.** Each day shows one muted line, "✓ 2 done", below the scheduled jobs. Tapping it shows the done jobs. They aren't numbered, can't be dragged, and never take up a spot, so a newly scheduled job can't land "on top of" a finished one.
- On past days, that collapsed line is the record of what happened.

**Drag and drop does all the scheduling.**
- **Library:** SortableJS, loaded from cdnjs at a pinned version. It's plain JavaScript, not React, and it handles touch, dragging between lists, and the animation that slides other cards out of the way (about 150 ms). Writing all of that by hand would cost hundreds of lines.
- **What a drag can do:**

  | Drag | Result |
  |---|---|
  | Within a day | Reorder |
  | Day → another day | Reschedule, placed where it's dropped |
  | Unscheduled panel → day | Schedule, placed where it's dropped |
  | Day → Unscheduled panel | Unschedule (the date is cleared) |

- **On phones,** you press and hold a card for about 200 ms to start dragging, so normal scrolling still works.
- **Saving:** each drop sends one fetch POST, which is allowed for in-place saves. If the save fails, the card snaps back and a short error message appears.
- **Month view has no drag.** It's only for looking ahead.

**Create jobs like Google Calendar.**
- Clicking empty space in a day column opens the job form with that date already filled in.
- A single `+ Job` button in the header opens it with no date.
- Clicking a card opens the same form for that job, with its history at the bottom.
- It's one modal. The modal's contents are a form drawn on the server and fetched as HTML. It saves with a normal form POST, and the page then reloads at the same week.

**Nothing is truly deleted.**
- **Archive.** Archived jobs disappear from every view except `/junk/manage/archived`, where each has a Restore button. A restored job goes back to where its date says: the end of that day's line, or the Unscheduled panel if it has no date.
- **History.** Every create, edit, reschedule, done/undone, archive and restore writes an append-only `JobEvent` row with who, when, and old → new for each changed field. Reorders within the same day aren't logged.

**One market, no school field.** Managers will be scoped to their school eventually, but everyone is on one market for now. Nothing here blocks adding a school field later.

**Access.** Add a new flag `User.is_junk_manager`. Use one guard, `junk_manager_required`, which allows users with `is_junk_manager` OR `is_super_admin`. Everyone with access has the same permissions. A junk manager who isn't an admin lands on `/junk/manage` after logging in and when hitting `/dashboard`. No accounts are created in this slice.

---

## Data Model (`junk/models.py`, importing `db` from `models`)

### `User` (existing, in `models.py`)
- `is_junk_manager`: Boolean, default False, `server_default='false'`, not null

### `Job` (table `junk_job`)
| Field | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `customer_name` | String(120) | nullable |
| `customer_phone` | String(30) | nullable. The crew texts this number. |
| `address` | String(255) | nullable, free text |
| `quote_amount` | Numeric(10,2) | nullable. Empty means "Needs quote". |
| `notes` | Text | nullable: stairs, gate code, what's going |
| `scheduled_date` | Date | nullable, Eastern calendar date |
| `queue_position` | Integer | nullable. Numbered 1..n among the day's jobs that aren't done or archived. |
| `completed_at` | DateTime UTC | nullable |
| `archived_at` | DateTime UTC | nullable |
| `created_by_id`, `archived_by_id`, `completed_by_id` | FK User | |
| `created_at`, `updated_at` | DateTime UTC | |

Index on `(scheduled_date, queue_position)`.

### `JobEvent` (table `junk_job_event`)
| Field | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `job_id` | FK Job | |
| `user_id` | FK User | |
| `created_at` | DateTime UTC | |
| `action` | String(20) | `created` / `updated` / `done` / `undone` / `archived` / `restored` |
| `changes` | JSON | `{field: [old, new]}` |

Migration: one Alembic migration for the `User` column plus both tables, using standard Postgres syntax. Also apply it to `campusswap_prod` locally.

---

## Routes (Blueprint `junk`, prefix `/junk`)

| Method | URL | Purpose |
|---|---|---|
| GET | `/manage` | Calendar. Takes `?view=week\|month` (default week) and `?date=YYYY-MM-DD` (default today, Eastern). |
| GET | `/manage/job/form` | Modal contents. `?id=` loads an existing job; `?date=` prefills a new one. |
| POST | `/manage/job` | Create a job |
| POST | `/manage/job/<id>` | Save edits. A date change appends the job to the end of the new day's line. |
| POST | `/manage/job/<id>/done` | `undo=1` reverses it. Undoing puts the job back at the end of its day's line. |
| POST | `/manage/job/<id>/archive` | Soft delete |
| POST | `/manage/job/<id>/restore` | |
| POST | `/manage/board/move` | JSON body `{job_id, date or null, ordered_ids}`, where `ordered_ids` is the full new order of the target day. Returns JSON. |
| GET | `/manage/archived` | Archived list |

- Every write that changes the line calls one helper, `_renumber_day(date)`, which renumbers that day 1..n.
- `board/move` checks that `ordered_ids` matches exactly the active jobs on the target day plus the moved job. If it doesn't (because two managers edited at once), it returns 409, and the page reloads with a "Calendar was updated, refreshed" message.

---

## UI

**Layout.** `junk/templates/junk/manage_layout.html` is standalone. It has a slim top bar with placeholder copy, a Calendar link and the user menu. Colors come from `static/style.css` variables only. All copy is placeholder; Henry owns the wording.

**Week view (default)**
- **Header:** `‹` `Today` `›` · "Nov 16 – 22" · `Week | Month` · `+ Job`
- **Seven columns,** Monday to Sunday, with today subtly highlighted.
- **Cards** show three things: the queue number, the customer name, and the address on one line, truncated if needed. That's all; quote and phone are in the modal. Clicking a card opens it, and dragging moves it.
- **The empty space** under the cards in each column is the click target for creating a job on that day.
- **Unscheduled panel** on the right: the same cards, oldest first, with a "Needs quote" tag where it applies.
- **Mobile:** the days stack vertically with the Unscheduled panel at the top, so it's in reach while dragging down. No horizontal scroll.

**Month view.** A plain grid. Each day shows a job count plus the first 2 names. Clicking a day opens that week.

**Job modal.** Fields: name, phone, address, quote, date, notes. Buttons: Save, Mark done / Undo done, and Archive (a quiet text link with a confirm step). History sits collapsed at the bottom, newest first, with times in Eastern.

---

## Out of Scope (later slices)
- Crew roles, migrating returning workers, invites, assigning crew to jobs (Slice 2)
- Crew portal (Slice 3)
- Customer records, texts/ETAs, photos, payments, crew pay (TBD, likely 40%), quoting rubric
- Day view with multiple trucks
- School/market scoping
- An archive reason (declined / cancelled / mistake)
- Creating the manager accounts

---

## Tests (`test_junk_calendar.py`, project root)
- **Guard:** anonymous → login; plain admin, worker or seller → denied; `is_junk_manager` → 200; super admin → 200
- **All-empty job:** creates fine, lands in Unscheduled with a "Needs quote" tag, and renders as "Untitled job"
- **Create with a date:** goes to the end of that day's line
- **Board moves:**
  - Reorder within a day
  - Cross-day move: dropped where placed, and the old day is renumbered with no gaps
  - Unscheduled → day
  - Day → Unscheduled: date and position cleared
- **Stale moves:** `board/move` with an `ordered_ids` list that no longer matches → 409, nothing changed
- **Done:**
  - Marking done takes the job out of the numbering, and the rest of the day renumbers
  - Undo puts it back at the end
  - A done job can't be moved by drag
- **Archive:**
  - An archived job is hidden from the calendar and Unscheduled, and shows on the Archived page
  - Restore puts it back by date, or into Unscheduled if it has no date
  - No route can hard-delete a job
- **History:** each mutation writes the correct `JobEvent` and diff; reorders within a day don't
- **Date boundaries:** a Sunday job shows in the correct Mon–Sun week; month view spans correctly
- **Must not wipe `campusswap_prod`.** Use the safe fixture pattern noted in the memory file `destructive-test-suites-wipe-prod-snapshot`.

---

## Revision 2 — Henry's first-pass feedback (2026-11-17)

These override anything above that conflicts with them.

**Separate site**
- **Own sign-in page** at `/junk/login`, with its own standalone layout. None of the legacy site's chrome appears on it.
- **`/junk`** redirects to the calendar.
- **Junk-only accounts are confined to `/junk`.** That means accounts with `is_junk_manager` and no admin, super admin or campus director role. Any other URL redirects them to `/junk/manage`, and `/logout` goes to `/junk/logout`, which returns to `/junk/login`. This is the `before_app_request` hook in `junk/routes.py`.

**Top bar**
- No brand text.
- A single "Calendar" tab with a quiet dropdown holding **Removed jobs**. It opens on hover; on touch, tapping the caret opens it.

**"Remove" replaces "Archive" everywhere in the UI**
- Routes are `/manage/job/<id>/remove` and `/manage/removed`; the restore button reads "Put back".
- Internals are unchanged: `archived_at` and the event action `archived`.
- The Removed jobs page is full width.

**Week view**
- The Unscheduled panel is on the **left**. Its "Drag a job here…" hint is always visible.
- **Cards show the quote**, or a "Needs quote" tag, instead of a queue number.
- **Done jobs look like normal cards, but green.** They sit at the **top** of their day, above the active line, and can't be dragged. The "✓ N done" line is gone.
- **The day's line fills its whole column,** so a drop anywhere in a column lands.
- **Fast-drag fix:** on release, the JS checks the column actually under the pointer and corrects the drop if SortableJS sampled a different one.
- **Today button:** only shown when the current week or month isn't on screen.

**Month view.** Each week row is a single link that highlights on hover and opens that week.

**Job form**
- The address field uses Google Places autocomplete (`GOOGLE_MAPS_API_KEY`, the same key the checkout uses).
- The modal is now a fixed overlay instead of `<dialog>`, because `<dialog>` renders above everything, so the Places dropdown would be hidden behind it.

## Revision 3 — second round of feedback (2026-11-17)

**Done is just a color.**
- A done job keeps its `queue_position` and stays where it is in its day's line; undo doesn't move it.
- Done jobs can be dragged like any other job, but can't be unscheduled. The Unscheduled panel won't accept them, and the server returns 409.
- **Future (out of scope):** a crew-set "waiting approval" (yellow) state, which a manager then confirms as done, from the calendar or a separate screen.

**No page reloads.** Arrows, Today, Week/Month, saves, done/undo and remove all fetch the page and swap the `[data-cal]` region in place. Hovering a nav link prefetches it, cached for 20 s and cleared on any write. Back and forward work through `pushState`/`popstate`. A save that errors keeps the modal open so nothing typed is lost.

**Drag is snap mode.**
- The lifted card follows the mouse. The dashed slot showing where it will land moves into whichever day is under the pointer immediately, stacking from the top of that day, and never slides across the gap between days.
- No column highlight while dragging (Henry: it looked better without it). The card snapping into the day is the only cue.
- Anywhere off the calendar (panel, toolbar, outside the window) counts as Unscheduled: the panel box lights up only then, and releasing there unschedules the job. A done job released off the calendar is put back instead (it must keep its date).
- After every drop the calendar re-renders from the server.

**Month view**
- It has the Unscheduled panel too.
- Every job in a day shows as a name chip; it's the same card element styled compactly, and rows grow to fit.
- Chips drag between days and to and from the panel.
- Clicking empty space in a week row opens that week.

**Today button** sits between the ‹ › arrows when it's shown.

## Revision 4 — delete means delete; Unscheduled is a queue (2026-11-17)

These supersede every earlier "archive", "Remove" and "Removed jobs" rule above.

**Delete is permanent.**
- The modal's Delete link asks "Delete this job? This can't be undone." and then deletes the job and its `JobEvent` history.
- The Removed jobs page, Put back, and the Calendar dropdown are gone; the top bar is a single Calendar tab.
- Migration `8b1f3c2d9a47` drops `archived_at`/`archived_by_id`, first hard-deleting any rows that were soft-deleted.

**Unscheduled is a queue.**
- `queue_position` also numbers the Unscheduled list (`scheduled_date IS NULL`).
- A job joins the bottom when it's created without a date, dragged off the calendar, or has its date cleared.
- The panel still can't be reordered by hand.

---

## Revision 5 — address picker + sign-in both ways (2026-11-18)

**Address.** The legacy `google.maps.places.Autocomplete` widget (`.pac-container`) is replaced by the
Places API (New): `AutocompleteSuggestion.fetchAutocompleteSuggestions` with a session token, rendered
in our own dropdown (`[data-addr-list]`, keyboard nav, matched text bold, "Powered by Google").
Picking a suggestion fetches `formattedAddress` + `location` and shows a small map preview (non-pannable,
center pin drawn in CSS, "Open in Google Maps"). New nullable `junk_job.address_lat` / `address_lng`
(migration `c4e7a2b19f05`) are set only from a pick; typing by hand clears them. They are not history fields.

**Sign-in.** `/junk/login` offers "Continue with Google" and email + password; every manager can use both.
- Google reuses the site's OAuth client: `/junk/login/google` sets `session['junk_oauth_next']`, and
  `app.auth_google_callback` hands off to `junk.routes.finish_google_login`, which only signs in existing
  junk managers (never creates accounts, rejects unverified emails) and links Google to the account.
- "Forgot or never set a password?" emails a one-hour, single-use link (signed over the current password
  hash) to set a password. The request page answers the same whether or not the email has access.
- POST limits on Render: login 20/hour, link request 5/hour (applied in app.py; Flask-Limiter isn't
  installed locally). The mailer is passed in as `app.extensions['junk_send_email']`.

---

## Revision 6 — legacy site locked to junk (2026-11-18)

Every Campus Swap page now redirects to `/junk/login` (signed-in junk managers go to `/junk/manage`).
No code was deleted; `junk/routes.py:_gate_legacy_site` gates it. On by default; set
`SITE_LOCKED_TO_JUNK=0` on Render to reopen. Off under TESTING unless a test sets the config flag.
- **Still open (machines call these):** `/junk`, `/static/`, `/uploads/`, `/favicon*`, `/health`, `/webhook`,
  `/sms/webhook`, `/admin/cron/*`, `/admin/digest/trigger`, `/unsubscribe/`.
- **`/auth/google`** only when the sign-in started on `/junk/login`, so the old flow can't create seller accounts.
- **Admins and super admins** pass through to the old site, for wrap-up work.
- **`robots.txt`** disallows everything.
