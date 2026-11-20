# Junk Removal — Slice 2: Crew

**Status:** 🟡 Step 4 built and awaiting review. Slice 3 is `feature_junk_jobsite.md`.
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

**3a — data, modal, cards** ✅ (0e32c2c)
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

**3b — crew panel + drag** ✅
- **Crew panel:** on the right on desktop (`.jr-board` columns are 250px | calendar | 190px), stacked under the calendar on narrower screens, and at the bottom on phones.
  - **Phones:** up to 3 rows of two, left to right. With more than 6 people it becomes 3 rows that fill down each column and scroll sideways, with the next column peeking in, so what's in view is a run of neighbours in the list.
  - It's hidden in phone month view, which has no chips to drop on.
  - It lists the Team page: managers on top, then crew, each alphabetical. Managers have dark initials and an amber star; on phones the star sits on the initials circle's corner, so names aren't cut off.
- **Drag a person onto a job** to assign them. The job under the pointer gets a dark outline. The panel keeps its copy.
- **Desktop only: drag a name pill off a card.**
  - Onto another job: moves the person, in one request (`action: 'move', from_job_id`). Each job's history records its own side.
  - Back onto the same card: nothing changes.
  - Anywhere else: unassigns them. The Crew panel turns green whenever letting go would remove them.
- **Phones:** a press on an initials bubble drags the job, not the person.
- **Job drags:** letting go of a job over the Crew panel puts it back; it doesn't unschedule it. No landing slot shows while the job is over the panel.
- **Dev only:** on phones the page gets 72px of extra bottom room, so the dev pill never covers the Crew strip.
- **Tests:** a test for move and one for the panel; 114 passing in total. Browser check covered panel → job, pill → job (move), pill → panel, pill → empty space, a job dropped on the Crew panel, and phone panel → job.

**At-a-glance pass (Henry, 2026-11-19)** — replaces the star and the managers-on-top order above
- **No manager favoritism.** The Crew panel puts *you* (the signed-in person) on top, then everyone else, managers included, by last name. David sees Cam in alphabetical order, and vice versa. The stars are gone everywhere; the Team page still labels roles.
- **Cards show name, street line and crew only.** The quote and "Needs quote" are off every card (desktop, phone, Unscheduled); the quote lives in the job modal.
- **Dragging a pill off a job (desktop):** onto another job moves the person. Let go anywhere else on the calendar grid and the pill goes back to its job. Off the calendar (Unscheduled, the Crew panel, the page around it) removes them. The Crew panel lights up only when letting go would remove someone.
- **"+ Add…" in the job modal is a searchable team picker,** not a native dropdown. It's a floating list (so the modal never scrolls), about 6 rows tall, that scrolls for the rest, ordered by last name. Typing narrows it by the start of any word of a name or email. On desktop the search box is focused straight away, and arrows plus Enter add someone. On phones no keyboard appears until you tap the search box, so you can just scroll. Classes are `jr-teampick-*`; the preview toolbar already uses `jr-pick`. It'll be reused for "Handed it to…" in Slice 3.
- **The Team page and the picker list everyone by last name;** managers don't go first.
- **"(me)" follows your own name** at the top of the Crew panel, in muted text; a long name gives way ("…") before it does.
- **The street line** is the address up to the first comma, plus a unit if one follows (`street_line()` in `junk/models.py`, filter `jr_street`): "829 Shearer St", "2100 Old Mason Farm Rd, Apt 3B". The full address is the card's tooltip.

### Step 4: Crew portal, the list (Henry, 2026-11-19)
**Phone first, laptop second.** Crew use this on the job, so the phone matters most here.

- `/junk/crew` is **a list, not a calendar.** Crew have a job or two a week. They open the app to see where they're going and what to do there.
- **Top: stats.** Total jobs done and total earned.
- **Today:** full cards, in calendar order (no times; the order within the day is the order). Each card shows:
  - the name
  - the street address, with a big **Navigate** button
  - big **Call** and **Text** buttons for the customer's phone
  - the notes, and who else is on the job
  - **Your cut:** 20% × quote, from `AppSetting junk_crew_pay_pct`. Crew don't see the quote itself; they see what they'll make.
- **Coming up:** compact rows (name, street, crew, cut), grouped by day. A tap opens the full card. Photos from the quote will go here later.
- **Done:** recent closed jobs.
- **Jobs with no date** don't show.
- **Read-only** in this step. The job-site checklist comes in Slice 3 (`feature_junk_jobsite.md`).
- **Crew don't quote, and don't change the quote.** Managers quote jobs beforehand.
- **As built:**
  - Pay comes from `crew_pay_pct()` / `crew_cut()` in `junk/jobs.py`.
  - The buttons are plain `tel:`, `sms:` and Google Maps directions links (filters `jr_tel`, `jr_maps`).
  - Days read `jr_day`: Today, Tomorrow, Sat, Nov 22.
  - Open jobs dated before today sit on top under **"Not finished yet"**: no date gates, and they still count until they're closed.
  - Coming up rows are plain `<details>`, so there's no JS.
  - The full address shows only when it adds something beyond the street line.
  - Totals count closed jobs only.
- **Later: open jobs crew can claim.** Leave room in the page for it: a list sorted by date or cut, or a calendar that shows the cut. It could be a section, a page or a modal; that's undecided.

**Answered 2026-11-18:**
- **More than 2 people on a job is rare.** The 40% labor cost of a 2-person job is the normal case.
- **A manager who works a job gets 20% too.** Pay goes to everyone assigned, whatever their role.

**3b follow-ups (Henry, 2026-11-18)**
- **Everyone on the team is light slate,** managers included (`--jr-person-bg`, mixed from `--slate`). A star marks managers on desktop pills and in the Crew panel; phone bubbles have no star.
- **On a done job, its crew turn dark green** (`--primary`) along with it.
- **Crew panel order:** managers on top, then crew, each sorted by last name. Punctuation is ignored, so "Manager (dev)" sorts as "dev".
- **Phone Crew panel:** the manager star follows the name, and a long name gives way ("…") before the star does.
- **After a drop, the calendar keeps page scroll and sideways strip scroll** (Unscheduled, Crew). Before this, the Crew strip snapped back to its first column.
- **Phone month view keeps the Crew panel hidden,** because there are no job chips to drop onto. Assign crew from week view.
