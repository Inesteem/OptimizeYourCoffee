# Refactoring Plan — v0.6

Consolidated from 3 independent reviews: Gemini (architecture), Claude JS reviewer, Claude Python reviewer.

## Consensus: All 3 reviewers agree on these top priorities

### 1. XSS via innerHTML (Critical — JS)
All 3 JS files use `innerHTML` with DB-sourced data. 5 injection points total.
- autocomplete.js: suggestion chips built from `/api/autocomplete` data
- tastingnotes.js: note suggestions from `/api/custom-tasting-notes`, chip rendering from DB values

**Fix:** Add `esc()` helper + use event delegation instead of per-element listeners.

### 2. Global dict mutation in render_tasting_notes (Critical — Python)
Every call mutates the module-level `TASTING_EMOJIS`. Stale entries never removed.

**Fix:** Build local merged dict with `dict(TASTING_EMOJIS)`.

### 3. Per-request DB connection via flask.g (Critical — Python)
~28 connections opened per page load on the index route. N+1 queries in coffee_stats.

**Fix:** `flask.g` pattern + `teardown_appcontext`. init_db/backup_db use direct connections.

### 4. DRY: Extract parse_coffee_form helper (Warning — Python)
~45 identical lines in add_coffee and save_coffee.

**Fix:** Single `parse_coffee_form(data)` returning a dict.

### 5. Emoji mapping drift between Python and JS (Warning — Architecture)
Python has 48 entries, JS has 60+. They diverge silently.

**Fix:** Single `tasting-emojis.json` loaded by both. Python loads at startup, JS fetches it.

### 6. PROCESS_OPTIONS not passed to templates (Warning — Python)
Defined in app.py but never injected. Hardcoded in 2 templates.

**Fix:** Add to `inject_globals()` context processor, use in templates.

## Additional findings by reviewer

### JS Reviewer (unique findings)
- W2: waitForKeyboard polling has no retry limit → add max 100 retries
- W3: Event listeners leaked on every keystroke → use event delegation
- W5: keyboard.js layout switch boilerplate repeated 6x → extract `switchLayout()` helper
- S3: Dead code in emoji stripping regex → use data-note attribute
- S4: Redundant `new Set(Object.keys(...))` → just `.sort()`

### Python Reviewer (unique findings)
- W4: Undo mechanism: single slot, 4KB session limit risk → size guard or soft-deletes
- W5: coffee_stats is 65 lines → split into build_chart_data + build_stats_summary
- W6: api_autocomplete f-string SQL → add frozenset guard
- S8: Magic numbers scattered → consolidate into config section
- S9: freshness_status inconsistent return → always return dict
- S10: diagnose if/elif chain → data-driven DIAGNOSIS_RULES
- S11: save_evaluation duplicated INSERT/UPDATE → use UPSERT
- S13: PROCESS_OPTIONS is dead code in app.py

### Gemini (unique findings)
- Split app.py only needed at ~1500 lines (currently ~950, fine for now)
- WTForms overkill for kiosk — simple helper is right pattern
- Fix DB pooling first before adding charts/recipes/ML features
- Codebase is "fundamentally sound" — issues are organizational, not architectural

## Implementation Order (estimated time)

| # | Task | Time | Impact |
|---|------|------|--------|
| 1 | XSS: add esc() helper to all 3 JS files | 15 min | Critical security |
| 2 | render_tasting_notes: stop mutating global | 3 min | Critical correctness |
| 3 | flask.g DB connection + teardown | 20 min | Critical performance |
| 4 | parse_coffee_form helper (DRY) | 12 min | High maintainability |
| 5 | tasting-emojis.json (single source of truth) | 20 min | High maintainability |
| 6 | PROCESS_OPTIONS via context processor | 5 min | Medium maintainability |
| 7 | Event delegation in JS (replace per-element listeners) | 10 min | Medium performance |
| 8 | keyboard.js switchLayout helper | 5 min | Low code quality |
| 9 | Magic numbers → config constants | 10 min | Low maintainability |
| 10 | UPSERT for save_evaluation | 5 min | Low code quality |

**Total: ~105 minutes for everything. Top 3 items: ~38 minutes.**
