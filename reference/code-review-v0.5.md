# Code Review — beta-v0.5

Reviewed 2026-04-03. 20 issues found. Status updated 2026-04-03.

## DONE: Critical (all fixed)

- [x] Hardcoded secret key → `os.urandom(32)` with env var override
- [x] SQL injection in undo → column allowlists
- [x] os.system → `subprocess.Popen()`

## DONE: High (5 of 6 fixed)

- [x] debug=True → `FLASK_DEBUG` env var
- [x] No input validation → `safe_int()`/`safe_float()` helpers
- [x] numpy → top-level import with try/except
- [ ] No CSRF protection — skipped (local kiosk, no auth, low risk)

## DONE: Medium (6 of 7 fixed)

- [x] Global dict mutation in render_tasting_notes → local merged dict
- [x] DRY: form parsing → `parse_coffee_form()` helper
- [x] DRY: process list → `PROCESS_OPTIONS` via context processor
- [x] innerHTML XSS → `esc()` helper + DOM methods + event delegation
- [x] waitForKeyboard → retry limit of 100
- [x] keyboard.js → `switchLayout()` helper (was 6x boilerplate)
- [ ] DRY: tasting emoji maps in Python AND JS — still separate (future: shared JSON)

## DONE: Low (2 of 4 fixed)

- [x] numpy import → top-level
- [x] Polling loops → retry limits added
- [ ] Magic number LIMIT 20 — still hardcoded
- [ ] N+1 DB connections — partially fixed (render_tasting_notes no longer opens connections, but flask.g not yet adopted)

## Remaining (low priority, deferred)

- CSRF: not needed for local kiosk
- flask.g: mechanical refactor, medium effort, low urgency
- Shared emoji JSON: nice-to-have, both sources work independently
- LIMIT 20: add pagination when users have 20+ samples per coffee
- API auth: not needed for local-only access
