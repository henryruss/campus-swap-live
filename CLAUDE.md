# Claude Code Instructions — Campus Swap

## Before Every Session
Read these files in order before writing any code:
1. `CODEBASE.md` — full route map, models, templates, existing patterns
2. `OPS_SYSTEM.md` — ops platform master reference (glossary, staffing model, roadmap)
3. `HANDOFF.md` — current build state, what's done, what changed from specs
4. The active spec file for this session (told to you at session start)

## Rules That Never Change
- Server-rendered only. No React. Vanilla JS for interactivity.
- All new templates extend `layout.html`.
- Never hardcode colors — use CSS variables from `static/style.css`.
- All forms include `{{ csrf_token() }}`.
- Database changes always get a Flask-Migrate migration.
- Ask before making any decision not covered by the active spec.