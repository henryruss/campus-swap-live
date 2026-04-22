# Feature Spec: /parents Landing Page + Instagram Sitewide

## Goal

Two small, independent changes shipped together:

1. **`/parents` page** — a public-facing landing page for UNC parents to learn about Campus Swap and forward a pre-written message to their student. No auth required. Not linked from the main nav. Distributed via Facebook groups and parent networks.

2. **Instagram link in `layout.html`** — surface `@campusswapunc` on Instagram everywhere on the site via the footer (and optionally the nav), since it currently appears nowhere.

No model changes. No migrations. No auth logic.

---

## New Routes

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `GET` | `/parents` | `parents` | Render the parent landing page. No login required. |

---

## Template Changes

### New: `templates/parents.html`

Extends `layout.html`. Full standalone marketing page. Content mirrors the approved mockup (`parents-landing-mockup.html`). Key sections:

- **Nav override** — `parents.html` should pass `hide_nav_links=True` (or equivalent context var) if `layout.html` supports suppressing nav links on marketing pages. If not, the default nav is fine — the page doesn't need to hide it.
- **Hero** — dark green background, eyebrow pill, headline, subhead, two CTA buttons, subtle scroll nudge link pointing to `#share`
- **Trust bar** — four cream pills: "100% free pickup", "50/50 earnings split", "Takes 5 minutes to sign up", "UNC Chapel Hill move-out"
- **How it works** — four-card grid: Snap a photo / We show up / We sell it / They get paid. Each card has an amber tag badge.
- **What they can earn** — dark green section, two-col layout. Left: headline + 50/50 split callout box + CTA. Right: earnings table card showing example items and a total row.
- **Forward this to your student** — cream background, pre-written text message in a styled bubble, three share buttons: Copy message (clipboard), Text it (`sms:` deep link), Email it (`mailto:` deep link). Copy button shows inline "✓ Copied" confirmation via JS.
- **Footer** — page-level footer (inside the template, not layout.html's footer) with Campus Swap wordmark, Instagram link, copyright, and links to Privacy/Terms/About.

**Styling notes:**
- Use CSS variables only (`--primary`, `--accent`, `--bg-cream`, `--sage`, etc.) — never hardcode hex values.
- Page-specific styles go in a `<style>` block inside the template (scoped to this page), not in `static/style.css`, since this is a one-off marketing page.
- The pre-written share message text and the `sms:`/`mailto:` hrefs should be consistent — same copy in all three.

**Share message copy (exact):**
> Hey! Move-out is coming up and I found something you need to know about. It's called Campus Swap — they show up with a truck, move all your furniture out for free, sell it to incoming students, and you keep 50% of everything that sells. Completely free to you. Takes 5 minutes to sign up: campusswapunc.com

---

### Modified: `templates/layout.html`

Add `@campusswapunc` Instagram link in **two places**:

**1. Footer** — add alongside the existing footer links. Render as a small linked item with an inline SVG Instagram icon:

```html
<a href="https://www.instagram.com/campusswapunc" target="_blank" rel="noopener">
  <!-- inline instagram svg icon -->
  @campusswapunc
</a>
```

Place it at the end of the existing footer link row, or on its own line if the footer has a separate "social" area. Match the existing footer link styling (muted color, hover state).

**2. Desktop nav** — add as a quiet secondary link to the right of the main nav links, left of the Sign In icon. Style it subtly — icon + handle, muted color, no button treatment. Should not compete with "Become a Seller" or "Shop The Drop".

**Mobile nav** — add `@campusswapunc` as a link at the bottom of the slide-in menu, below the auth-conditional items. Icon + handle. Opens in new tab.

**Instagram icon:** Use an inline SVG (no external library dependency):
```html
<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
  <rect x="2" y="2" width="20" height="20" rx="5" ry="5"/>
  <circle cx="12" cy="12" r="4"/>
  <circle cx="17.5" cy="6.5" r="0.5" fill="currentColor" stroke="none"/>
</svg>
```

---

## Route Implementation

```python
@app.route('/parents')
def parents():
    return render_template('parents.html')
```

No login required. No context variables needed beyond what `layout.html` already injects globally. Place the route near other public marketing routes (e.g., near `/about`).

---

## Business Logic

None. This page is purely informational. No forms that submit to the server, no session reads, no DB queries.

The Copy/Text/Email share buttons are all client-side only:
- **Copy:** `navigator.clipboard.writeText(...)` with an inline JS confirmation toggle.
- **Text:** `<a href="sms:?body=...">` — opens native SMS app on mobile with pre-filled body. No-op on desktop.
- **Email:** `<a href="mailto:?subject=...&body=...">` — opens default mail client.

---

## Constraints

- Do not add `/parents` to the main nav, footer link list in `layout.html`, or any sitemap. It is a dark page — shared manually, not surfaced in product UI.
- Do not add any login gates, redirect logic, or flash messages to this route.
- Do not modify `static/style.css` — all page-specific styles stay scoped inside `parents.html`.
- The Instagram changes to `layout.html` must not break existing nav layout on mobile or desktop. Test both hamburger menu and desktop nav after the change.
- `target="_blank"` on the Instagram link must include `rel="noopener"`.
