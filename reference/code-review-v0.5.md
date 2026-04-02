# Code Review — beta-v0.5

Reviewed 2026-04-03. 20 issues found.

## TODO: Critical (fix first)

- [ ] **Hardcoded secret key** — `app.secret_key = "coffee-sampler-2026"` → use `os.urandom(32)` or env var
- [ ] **SQL injection in undo** — column names from session interpolated into SQL. Add allowlists (`COFFEE_COLUMNS`, `SAMPLE_COLUMNS`, `EVALUATION_COLUMNS`)
- [ ] **os.system shell command** — `os.system("pkill ...")` → use `subprocess.Popen(["pkill", ...])`

## TODO: High (fix before sharing)

- [ ] **debug=True in production** — hardcoded with `host=0.0.0.0`. Exposes Werkzeug debugger (arbitrary code execution). Use env var `FLASK_DEBUG`
- [ ] **No input validation on numeric fields** — bare `int()`/`float()` on form data → unhandled ValueError on bad input. Add `safe_int()`/`safe_float()` helpers
- [ ] **No CSRF protection** — forms have no tokens. Add Flask-WTF or lightweight guard
- [ ] **N+1 DB connections in index()** — opens 2 connections + 20+ more via `render_tasting_notes` and `coffee_rating` per coffee

## TODO: Medium

- [ ] **Global dict mutation in render_tasting_notes** — mutates `TASTING_EMOJIS` on every call. Build merged dict locally instead
- [ ] **DRY: duplicated coffee form parsing** — `add_coffee()` and `save_coffee()` have ~35 identical lines. Extract `parse_coffee_form()` helper
- [ ] **DRY: tasting emoji maps in Python AND JS** — maintain one canonical JSON file, load from both
- [ ] **DRY: process list in two templates** — define once in Python context processor
- [ ] **Double DB connection in new_sample()** — use single connection
- [ ] **Unprotected API endpoints** — `/api/coffees`, `/api/samples` exposed to network
- [ ] **innerHTML with DB data (stored XSS)** — autocomplete.js and tastingnotes.js use innerHTML with data from DB. Escape HTML or use textContent

## TODO: Low

- [ ] **Cache-bust via timestamp** — every restart forces full re-download. Use git hash or content hash instead
- [ ] **numpy imported inside function** — ~150ms latency spike on first grind suggestion. Move to top-level with try/except
- [ ] **No per-request connection management** — use `flask.g` + `teardown_appcontext` instead of `get_db()` creating new connections
- [ ] **Polling loops with no retry limit** — `waitForKeyboard()` in JS spins forever if keyboard fails to load
- [ ] **Magic number LIMIT 20** — hardcoded in sample queries with no pagination
- [ ] **Service file path mismatch** — points to `~/coffee-app/` (deployed) vs `~/Documents/coffee-settings/coffee-app/` (source)
