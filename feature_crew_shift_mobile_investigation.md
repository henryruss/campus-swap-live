# Bug Investigation: Crew Shift View — Stop List Disappears on Mobile

**Type:** Investigation / Diagnosis  
**Priority:** High (driver-reported, affects live shift ops)  
**Status:** No confirmed fix yet — diagnosis first, patch second

---

## Problem Statement

Drivers report that the shift view (`/crew/shift/<id>`) intermittently stops showing stop cards — address, item list, and item IDs become blank or invisible. A full page refresh restores them temporarily. The bug appears mobile-only. Replication on a desktop browser (or even a desktop pretending to be mobile via DevTools) did not reproduce it.

---

## What We Know About the Page

`crew/shift.html` and `crew/stops_partial.html` together power this view. The relevant mechanics:

- On page load, the full stop list is server-rendered inside `#stop-list`.
- A **30-second `setInterval`** fires a `fetch()` to `GET /crew/shift/<id>/stops_partial` and replaces `innerHTML` of `#stop-list` with the returned HTML partial.
- The partial is rendered from `crew/stops_partial.html` — no layout, just the stop rows for the current mover's truck.
- Vanilla JS handles inline notes reveal and the issue-type picker; both rely on DOM elements being present after each refresh.

---

## Hypotheses (Ranked by Likelihood)

### 1. ⚠️ The auto-refresh fetch is silently failing and wiping `#stop-list`

**Most likely culprit.** If the `setInterval` fetch errors out (network blip, server timeout, auth issue) and the error handler unconditionally sets `innerHTML` to an empty or error string, the stop list goes blank. On mobile cellular, transient network failures are common — a 500ms gap in signal during the 30s poll is enough. Desktop on WiFi would rarely trigger this.

**What to look for in `crew/shift.html`:**
```js
// Dangerous pattern — no error guard:
setInterval(() => {
  fetch('/crew/shift/{{ shift.id }}/stops_partial')
    .then(r => r.text())
    .then(html => {
      document.getElementById('stop-list').innerHTML = html; // ← wipes on empty response
    });
}, 30000);
```
If `html` is an empty string (server returned 200 with empty body), or if the `.then()` runs on a non-OK response, the stop list is cleared.

**Fix pattern:**
```js
setInterval(() => {
  fetch('/crew/shift/{{ shift.id }}/stops_partial')
    .then(r => {
      if (!r.ok) throw new Error('Non-OK response');
      return r.text();
    })
    .then(html => {
      if (html.trim().length > 0) {
        document.getElementById('stop-list').innerHTML = html;
      }
      // If empty string returned, silently skip — keep what's already shown
    })
    .catch(() => {
      // Network error or non-OK — do nothing, keep existing DOM
    });
}, 30000);
```

### 2. ⚠️ `crew_shift_stops_partial` returns empty HTML under certain conditions

The partial route filters stops by the mover's `truck_number`. If there's a session edge case, a re-auth, or a DB query that returns nothing (e.g., a join condition fails silently), the server may return an empty response with a 200 OK. The fetch succeeds, but `innerHTML` gets cleared.

**What to check in `app.py` → `crew_shift_stops_partial`:**
- Does the route re-validate `current_user.id` against the shift assignment on every call?
- Is `truck_number` looked up fresh from DB each call, or cached in session? If a worker's `ShiftAssignment.truck_number` is `None`/`0`, the filter would return zero stops.
- Does the route return a proper 403/404 vs. empty 200 on edge cases?

### 3. Mobile browser tab backgrounding / service worker interference

iOS Safari aggressively suspends background tabs. If a driver locks their phone mid-shift and comes back, the `setInterval` may fire immediately on wake with a stale session cookie. If the Flask session has expired or `@login_required` is triggered, the partial route might redirect to `/login` (returning HTML that isn't stop cards). The `innerHTML` would then show the login page HTML injected into `#stop-list`.

**What to check:** Does `crew_shift_stops_partial` return a proper 401/403 JSON response rather than an HTML redirect when the session is gone? A `fetch()` following a redirect to `/login` would return the login page HTML as a successful response — the `r.ok` check passes, and the login page HTML gets injected into the stop list.

### 4. JS re-execution after innerHTML replacement wipes expanded UI state

Lower priority. When `innerHTML` is replaced, any event listeners attached to stop card elements (notes reveal, issue picker) are torn down and re-attached. If the re-attachment code fails silently (e.g., `querySelectorAll` finds nothing because stop cards haven't re-rendered yet due to async), subsequent taps on "Completed" or "Flag Issue" don't work — which could look like items "disappearing" if the driver interprets unresponsive UI as blank content.

---

## What to Actually Look At in Code

Claude Code should audit these specific things — **no changes yet, just read and report:**

1. **`crew/shift.html`** — find the `setInterval` block. Copy out the exact fetch + innerHTML logic. Does it have error handling? Does it guard against empty responses?

2. **`app.py` → `crew_shift_stops_partial`** — the `GET /crew/shift/<id>/stops_partial` route. What happens if:
   - The user's session expires mid-shift? (Does it redirect to login or return 401?)
   - `truck_number` is None or 0?
   - The shift has zero stops for this truck?
   Does it return empty 200, or proper error codes?

3. **`crew/stops_partial.html`** — what does it render when the stop list is empty? Empty string? An empty `<div>`? A "no stops" message?

---

## Recommended Fix (Once Diagnosis Confirms #1 or #3)

### For hypothesis #1 (empty/error response wiping DOM):
- Add `.catch()` to the fetch — on any network error, do nothing (keep current DOM).
- Add a non-empty guard — only replace `innerHTML` if the returned HTML is non-trivial (e.g., `html.trim().length > 50` as a rough check, or check for a sentinel string like `data-stops-loaded`).

### For hypothesis #3 (session expiry → login page injected):
- `crew_shift_stops_partial` should return `401` JSON `{"error": "session_expired"}` (not an HTML redirect) when unauthenticated.
- Client-side: check `r.ok` and `r.status !== 401` before injecting; on 401, show a non-destructive banner ("Tap to refresh — session expired") without clearing the stop list.

---

## No Model or Migration Changes Needed

This is a JS/route-level fix only. No DB changes.

---

## Constraints

- Do not change the 30s polling architecture — it's the right approach for this use case.
- Do not add React or any framework.
- Do not touch `crew_shift_stop_update` (the POST route for marking stops complete) — that's working fine.
- The fix must be safe for two movers on the same truck seeing the same stop list.

---

## Handoff Note

Before writing any fix, Claude Code should paste the current `setInterval` block and the `crew_shift_stops_partial` route body here for review. The diagnosis should be confirmed before any code is changed.
