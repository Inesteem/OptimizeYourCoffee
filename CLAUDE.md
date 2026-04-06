## Project Summary

**Coffee Sampler (OptimizeYourCoffee)** — a touchscreen espresso sampling and optimization app for Raspberry Pi.

Solves the problem of systematically tracking espresso shots, evaluating flavors, and dialing in grind settings for home baristas who brew 1-3 shots daily. Replaces pen-and-paper coffee journals with an interactive kiosk.

**Stack:** Python 3 / Flask / SQLite / Chart.js / simple-keyboard. Runs as a Chromium kiosk on Wayland (800x480 DSI touchscreen).

**Entry points:**
- `coffee-app/app.py` — Flask application (~2680 lines), all routes and business logic
- `./deploy.sh` — safe deploy to Raspberry Pi (backs up DB, stops Flask, syncs, restarts)
- `python3 -m pytest tests/test_app.py` — test suite (256 tests)

## Project Context

### Setup
```bash
pip install flask numpy    # numpy is optional (grind suggestion degrades gracefully)
```

### Run locally
```bash
python3 coffee-app/app.py   # http://localhost:5000 (debug off by default)
FLASK_DEBUG=1 python3 coffee-app/app.py  # with debug mode
```

### Run tests
```bash
python3 -m pytest tests/test_app.py -v      # full suite (256 tests, ~16s)
python3 -m pytest tests/test_app.py::TestFreshnessStatus -v  # single class
```

### Deploy to Pi
```bash
cp deploy.conf.example deploy.conf   # fill in PI_USER, PI_HOST, PI_APP_DIR
./deploy.sh                          # safe deploy with DB backup
```

### Environment variables
- `FLASK_SECRET_KEY` — session encryption key (optional; auto-generated to `.secret_key` file if unset)
- `FLASK_DEBUG` — set to `1` to enable debug mode (default: off)

### Non-obvious requirements
- **Raspberry Pi 4** with official 7" DSI touchscreen (800x480)
- **Chromium on Wayland** — has rendering bugs with `position: fixed` + `display: none` (see Wayland workarounds below)
- **fonts-noto-color-emoji** package on Pi for emoji rendering
- **numpy** optional — `suggest_grind()` falls back gracefully if missing

## Architecture

```
coffee-settings/
├── coffee-app/           # Flask application
│   ├── app.py            # ALL routes, models, helpers, migrations (~2500 lines)
│   ├── static/           # CSS, JS modules, Chart.js, data files, icons
│   │   ├── keyboard.js       # Virtual keyboard (wraps simple-keyboard)
│   │   ├── autocomplete.js   # Inline chip autocomplete for form fields
│   │   ├── tastingnotes.js   # Tasting note chip input with emoji lookup
│   │   ├── coffeeinfo.js     # Variety/process/bean info popups + roast guide + origin map preview
│   │   ├── coffee-info.json  # 117 varieties (scraped from WCR catalog) + 16 processes
│   │   ├── coffee-info-manual.json  # Hand-curated varieties (merged on top at load time)
│   │   ├── varieties.json    # 132 cultivar names for autocomplete
│   │   └── maps/             # SVG origin country map icons (46 countries)
│   └── templates/        # 12 Jinja2 templates (step1-3, edit, stats, insights, settings_notes, settings_grind, settings_taste, settings_design)
├── reference/            # Domain knowledge docs (tracked in git)
├── notes/                # Process artifacts (gitignored)
├── scripts/              # Build-time tools (map generation)
├── tests/                # pytest suite
├── deploy.sh             # Safe deploy script
├── deploy.conf           # Pi credentials (gitignored)
└── deploy.conf.example   # Template
```

### Components
- **app.py** — monolithic Flask app. Routes organized by section comments: coffee CRUD → sample CRUD → evaluation → stats → insights → settings → API → quit. Business logic functions (`freshness_status`, `diagnose`, `suggest_grind`, `coffee_rating`, `parse_coffee_form`) are defined before routes.
- **Static JS modules** — each an IIFE. Communicate via `window.coffeeKbd` (keyboard exposes `onChange`, `setInput`, `suppressDismiss` for autocomplete/chips to hook into).
- **Templates** — Jinja2 with `{{ v }}` cache busting. Chart.js instances created inline in `<script>` blocks with server-rendered JSON data.

### Data flow
1. Coffee overview (step1) → tap card → sample form (step2, pre-filled from recipe)
2. Sample saved with `days_since_roast` snapshot → redirect to evaluation (step3)
3. User can navigate back from eval to edit sample brew params, and forward again (loop via `from=eval` context)
4. Evaluation saved with UPSERT → redirect to `/evaluate/<id>/results` (dedicated results page showing diagnostics + scores)
5. Results page has Update (re-open eval form) and Leave (go to coffee overview) buttons
6. Stats page: per-coffee charts from aggregated query data
7. Insights page: cross-coffee groupings (process, origin, roast level) with Chart.js

### Grind aroma prefill
Grind aroma (1-5 score) and grind smell descriptors are captured on the sample page and carried to the evaluation page. They are **not stored on the `samples` table** — only persisted when the user saves the evaluation (to `evaluations.grind_aroma` and `evaluations.aroma_descriptors`).

Prefill priority chain (both sample and eval pages):
1. **Existing evaluation** — when re-editing, the saved values take precedence (template logic)
2. **Query params** — fresh selections from the sample page, passed via URL on redirect
3. **Sticky from last eval** — last evaluation of the same coffee (per-coffee carry-forward)

This means grind aroma "sticks" across shots of the same coffee, while fresh selections from the sample page always override the sticky value on the eval page.

### Database
Single SQLite file (`coffee.db`, WAL mode, foreign keys). 5 tables: `coffees`, `samples`, `evaluations`, `custom_tasting_notes`, `app_settings`. Schema migrations via `ALTER TABLE` in `init_db()` — **never drop/recreate tables** (user has real data).

**Soft-delete:** `coffees`, `samples`, and `evaluations` all have a `deleted_at` TEXT column (ISO timestamp or NULL). Delete routes set this timestamp rather than removing rows. Undo routes clear it (matching by timestamp). A maintenance page in Settings allows permanent purge of soft-deleted rows. All normal queries filter `WHERE deleted_at IS NULL`.

### Grind optimizer
Three selectable algorithms in Settings → Grind Optimizer, all dispatched via `suggest_grind()`:
- **Best Shots** (`weighted_centroid`): Weighted average of top-scoring shots with time-decay. Default.
- **Smart Curve** (`bayesian_quadratic`): Ridge regression with configurable regularization + optional recency. Pure Python.
- **Classic Curve Fit** (`quadratic`): Standard quadratic regression via numpy. No recency, no regularization.

All share:
- Configurable score source (overall, taste avg, ratio accuracy, single dimension)
- Recipe-matching filter (temp/dose tolerance to exclude shots from different brew setups)
- Cross-coffee prior for sparse data (fallback grind from similar coffees on the same grinder)
- Shot reliability weighting (channeling down-weighted, output outliers penalized)
- Settings stored in `app_settings` table as JSON via `get_setting()`/`set_setting()`

**Sparse data constraint:** A 250g bag yields ~14 shots at 18g dose. Algorithms must produce useful results with as few as 1-3 data points per coffee. This means:
- Never discard shots entirely — weight them down instead (channeled shots get 0.3, not 0)
- Cross-coffee prior is essential for new coffees (no single-coffee data yet)
- Outlier detection needs very low thresholds (2+ shots at same grind, not 3+)
- Prefer robust methods (weighted averages, ridge regression) over methods needing large samples
- All algorithmic improvements must be evaluated against this sparsity reality

Preview API (`/api/grind-preview`) runs algorithms on example scenarios in an in-memory SQLite DB.

### State
- **Database** — `~/coffee-app/coffee.db` on Pi (gitignored, backed up to `backups/` on every startup + deploy)
- **Session** — Flask cookie-based (undo state). Secret key in `.secret_key` file.
- **Static data** — `coffee-info.json`, `varieties.json`, `maps/*.svg` + `origin-map-index.json` (checked in, loaded client-side/server-side)

### Key design decisions
- **Monolithic app.py** — deliberate for a single-developer kiosk project. At ~2500 lines; consider splitting if it grows significantly further.
- **Inline chart JS** — server renders JSON into template `<script>` blocks. Avoids extra API calls.
- **Autocomplete as inline chips** (not floating dropdown) — Chromium/Wayland repaint bug prevents `position: fixed` elements toggled via display.
- **`days_since_roast` snapshot on samples** — frozen at creation time, not computed live. Shows bean age when that specific shot was pulled.
- **Grind aroma lives on evaluations, not samples** — captured on the sample page for UX but only persisted to `evaluations` on save. Carried between pages via query params, with sticky prefill from the last eval of the same coffee.
- **Eval results page** — saving an evaluation redirects to `/evaluate/<id>/results`, a dedicated page showing diagnostics and scores. Update returns to the eval form; Leave goes to coffee overview.
- **Unified edit UX** — editing a sample or evaluation uses Cancel (red) + Update buttons; no back arrows on edit pages.
- **Undo banner** — dismissible with × button. State stored in `sessionStorage` so it persists across the redirect after a delete. Cleared automatically on navigation away from the affected coffee.
- **Channeling field on samples** — `samples.channeling` TEXT column captures (none/some/unsure/unknown). Used as a reliability signal by all grind algorithms via `_shot_reliability()`.
- **Descriptor sentiment** — grind smell, brew smell, and taste descriptors carry good/neutral/bad sentiment. Chips are color-coded: green (good), default (neutral), red (bad).
- **Temp step** — temperature input increments by 0.1°C (previously 0.5°C) for finer control.
- **Sample history buttons** — Edit (yellow) and Delete (red) buttons in the history table, 8px gap between them.
- **Timestamped backups** — every Flask startup creates `coffee-YYYY-MM-DD_HHMMSS.db`. Pruned after 60 days.
- **Settings auto-save** — grind optimizer settings page saves on every change via debounced fetch (no save button). Route returns JSON for auto-save (`X-Auto-Save` header), redirect for manual POST.
- **Score-source-dependent UI** — grind settings page swaps algorithm cards based on selected score source. Ratio accuracy shows a dedicated "Directed Search" algorithm; all taste-based sources show the 3 generic algorithms.
- **Diagnostics vs optimizer separation** — `diagnose()` provides observational feedback (what went wrong), grind optimizer provides statistical next-shot suggestions. Diagnostics no longer give grind step advice.
- **Freshness roast-level windows** — `FRESHNESS_WINDOWS` dict maps bean_color to (degas, best_after, peak_dur, good_dur, consume_within). Default (no bean_color) assumes espresso roast (Medium-Dark). User-set best_after/consume_within override roast-level defaults; NULL means auto.
- **Opened-date acceleration** — penalty added to effective days_since_roast (0-7d open: 0, 8-14d: +5, 15-21d: +12, 22+: +20). Real `days` preserved for display.
- **Origin map icons** — 46 SVG continent silhouettes with highlighted country, generated from Natural Earth 110m via `scripts/generate_origin_maps.py`. Index loaded at startup via `ORIGIN_MAP_INDEX`.
- **Card design settings** — 3 selectable card layouts (Modern, Showcase, Legacy) stored in `app_settings`. Showcase has large 72px map spanning identity+flavor zones.
- **Roast guide overlay** — fullscreen overlay created/removed via DOM (Wayland-safe). Triggered by tapping "Bean Color" label (info-link pattern, no ⓘ icons).

## Key Conventions

### Database safety (CRITICAL)
- **NEVER delete or reset `coffee.db`** — user has real production data
- **Always deploy via `./deploy.sh`** — backs up DB, excludes `*.db` from rsync
- Migrations are idempotent: check `PRAGMA table_info` before `ALTER TABLE`
- Use `safe_int()`/`safe_float()` for all form input parsing — never bare `int()`/`float()`

### SQL injection prevention
- Column names in dynamic SQL validated against allowlists: `COFFEE_COLUMNS`, `SAMPLE_COLUMNS`, `EVALUATION_COLUMNS`
- Values always use `?` parameterized queries
- `parse_coffee_form()` returns a fixed dict — column names are never user-controlled

### HTML escaping
- JS files use `esc()` helper for all `innerHTML` with DB-sourced data
- Event delegation preferred over per-element listeners (performance + memory)
- Chip rendering uses DOM methods (`createElement`, `textContent`) not `innerHTML`

### Info popups
- Form labels (e.g., "Bean Color", "Process", "Variety") are the tappable element — styled with `info-link` (yellow, underlined). Do not use separate ⓘ icons next to labels.
- **Must `removeAttribute('for')` on info-link labels** — otherwise tapping the label focuses the associated input/select, which triggers the outside-click dismiss handler and closes the popup immediately.
- **300ms open guard** — `popupOpenedAt` timestamp prevents the same tap that opened a popup from also closing it (touchscreens fire both `pointerdown` and `click` from one tap).
- Outside-click uses `click` event (not `pointerdown`) so scrolling doesn't dismiss popups.
- Popups have a × close button for explicit dismissal.
- Info popups on detail pages use `info-link` class on the data span itself (variety, process names)
- Roast guide and bean size guide use fullscreen overlays (`roast-guide-overlay`) created/removed via DOM — Wayland-safe
- Variety data loaded from two JSON files: `coffee-info.json` (scraped catalog) + `coffee-info-manual.json` (hand-curated), merged at load time with manual winning on conflicts.

### Chromium/Wayland workarounds
- No `display: none` → `display: block` toggling on fixed/absolute elements — use `:empty` CSS collapse
- Autocomplete chips are regular inline DOM, not floating overlays
- `--disk-cache-size=1 --aggressive-cache-discard` on Chromium launch
- Asset cache busting: `?v={{ v }}` where `v` = `CACHE_BUST` (startup timestamp)
- **Touch events**: a single tap fires both `pointerdown` and `click`. Use `click` for dismiss handlers (not `pointerdown`) and add a timing guard when opening popups to prevent the opening tap from immediately closing them.

### Error handling
- No exceptions for flow control. Routes redirect on invalid input.
- `safe_int(val, default)` / `safe_float(val, default)` return default on failure
- `try/except` around date parsing in freshness calculations
- numpy absence handled gracefully via top-level `try: import numpy` with fallback

### Naming
- Python: `snake_case` functions, `UPPER_CASE` constants, `PascalCase` absent (no classes)
- JS: `camelCase` functions/variables, `UPPER_CASE` constants
- CSS: kebab-case, BEM-ish (`.coffee-card-top`, `.eval-btn`, `.grind-hint`)
- Templates: `step1_coffee.html`, `step2_sample.html`, `step3_evaluate.html` (workflow order)

### Patterns that look wrong but are intentional
- `with get_db() as conn:` opens a new connection each time (not `flask.g`) — deferred refactor, works fine for single-user kiosk
- `TASTING_EMOJIS` dict in Python is separate from `NOTES` in JS — they drift slightly (deferred: shared JSON)
- `CACHE_BUST` (not `APP_VERSION`) is a Unix timestamp — forces fresh assets on every restart, not semantically versioned

## PII Protection

- This repository is public on GitHub (Inesteem/OptimizeYourCoffee).
- Git history was scrubbed with `git-filter-repo` — no real names, IPs, or passwords.
- `deploy.conf` contains real Pi IP/username — gitignored.
- `.secret_key` — gitignored.
- Always use `DEPLOY_USER` / `PI_HOST_IP` as placeholders in checked-in files.
- Before pushing: `git diff --cached | grep -i "192\.168\|password\|secret"` to verify.

## Testing Configuration

- **Framework:** pytest
- **Runner:** `python3 -m pytest tests/test_app.py -v`
- **Structure:** `tests/test_app.py` — single file, 229 tests in 34 test classes
- **Naming:** `TestClassName` classes, `test_descriptive_name` methods
- **Fixtures:** `client` (Flask test client), `tmp_db` (temp SQLite file via `tmp_path`)
- **Mocking:** `unittest.mock.patch` for `subprocess.Popen` (quit route), no date mocking (uses relative dates)
- **No CI configured** — run locally before committing
- **No known flaky or skipped tests**
- **Coverage policy:** All logic (DB access, algorithms, business rules) must have thorough test coverage. UI is tested manually by the user — no UI tests needed.
- **Algorithm verification:** New algorithms (grind optimization, freshness model, diagnostics, rating tiers) should be reviewed by external agents to verify they make sense before merging.

## Code Style

- **Languages:** Python 3.11+ (backend), JavaScript ES6+ (frontend), CSS3, Jinja2 (templates)
- **Functions:** `snake_case` (Python), `camelCase` (JS)
- **Constants:** `UPPER_CASE` (both Python and JS)
- **Files:** `snake_case.py`, `camelcase.js`, `kebab-case.html/css/json`
- **Test files:** `test_app.py`, test classes `TestPascalCase`, methods `test_snake_case`
- **No max line length enforced** — generally ~100-120 chars
- **Import order:** stdlib → third-party → local (alphabetical within groups)
- **No written style guide** — follow existing patterns in the file

### Project-specific patterns a newcomer would get wrong
- Using `innerHTML` with DB data → must use `esc()` helper or DOM methods
- Adding a coffee field → must update: schema, migration, `parse_coffee_form()`, `COFFEE_COLUMNS` allowlist, both templates (add + edit), and tests. If the field supports soft-delete semantics, add `deleted_at` handling to delete/undo routes and the maintenance purge query.
- Deploying with `scp` instead of `./deploy.sh` → can corrupt the live database
- Using `display: none/block` for dynamic UI → won't work on Chromium/Wayland, use `:empty` or opacity
- Adding a new grind algorithm → must add: algorithm function, dispatch case in `suggest_grind()`, algorithm card in `settings_grind.html`, preview support, tests
- Adding a new score source → must add: entry in `SCORE_SOURCES`, handler in `_extract_score()`, any needed columns in preview API's in-memory schema
- Adding a new card design → must add: template branch in `step1_coffee.html` (conditional on `card_design`), CSS classes, option in `settings_design.html`, validation in `save_design_settings()`
- Adding a new coffee-producing country → run `scripts/generate_origin_maps.py` after adding it to `COFFEE_COUNTRIES` list; also add aliases to `ALIASES` dict
- Using `.get()` on sqlite3.Row → will crash; use bracket access `row["col"]` or try/except
- Adding a new variety → add to `coffee-info-manual.json` (not `coffee-info.json` which is scraped) and to `varieties.json` for autocomplete
- Making a form label tappable for info → must `removeAttribute('for')` or the label will focus the input and dismiss the popup

## Code Quality

- Run tests before committing: `python3 -m pytest tests/test_app.py`
- No linter currently configured — follow existing code style
- Pyright reports some false positives on SQLite Row dict access — these are known/accepted
- Keep cyclomatic complexity low; extract helpers rather than nesting conditionals
- The `diagnose()` function is the most complex — uses a priority chain of taste descriptors → score dimensions → brew time → output deviation

## Linter Configuration

No linter is currently configured for this project. Follow existing code style conventions.

<!-- TODO: consider adding ruff with pyproject.toml -->

## Type Checker Configuration

No type checker is formally configured. Pyright (via IDE) reports warnings but is not enforced.

Known accepted Pyright issues:
- `sqlite3.Row` dict access reports false `reportArgumentType` errors for float/int assignments
- These appear on `stats["avg_score"]` style assignments where Pyright infers dict value type incorrectly

## Formatter Configuration

No code formatter is configured. Follow existing indentation (4 spaces Python, 4 spaces JS/HTML).

<!-- TODO: consider adding ruff format or black -->

## Documentation Strategy

| Document | Location | Purpose | Update when |
|----------|----------|---------|-------------|
| README.md | repo root | Feature overview, schema, deployment | New features, schema changes |
| SETUP.md | repo root | Full Pi installation guide | Setup steps change |
| CLAUDE.md | repo root | Agent conventions and architecture | Architecture or workflow changes |
| reference/coffee-varieties.md | reference/ | 60+ varieties, 16 processes | New variety/process knowledge |
| reference/coffee-freshness.md | reference/ | Degradation science | Freshness model changes |
| reference/extraction-diagnostics.md | reference/ | Taste→grind mapping rules | Diagnostic logic changes |
| reference/espresso-evaluation.md | reference/ | Scoring framework | Evaluation fields change |
| reference/grind-optimization.md | reference/ | 4 grind algorithms, score sources, filters | Algorithm changes |
| reference/algorithm-improvements.md | reference/ | Improvement backlog + implementation status | New improvements |
| reference/coffee-rating-labels.md | reference/ | SCA scoring tiers | Rating logic changes |
| reference/tasting-note-labels.md | reference/ | Emoji mappings | New tasting notes |
| reference/altitude.md | reference/ | Altitude label → meter range by latitude | Altitude resolution logic changes |
| scripts/generate_origin_maps.py | scripts/ | SVG map icon generator | New countries, map styling |
| scripts/resolve_altitude.py | scripts/ | Altitude label resolver utility | Altitude bands change |
| scripts/extract_coffee_data.py | scripts/ | WCR catalog PDF extractor | Re-extract after catalog update |

All docs are developer-facing. No generated docs. No external wiki. No formal documentation review process — update docs alongside code changes.

## Multi-Agent Workflow

- Re-read the current file state before every write — never patch from stale context
- Assign tasks with clear, non-overlapping file boundaries to avoid merge conflicts
- Announce which files you intend to modify before starting work on a task
- Keep task descriptions self-contained: include file paths, expected inputs/outputs, and acceptance criteria
- Prefer many small isolated tasks over one large task touching many files simultaneously
- **Always run `python3 -m pytest tests/test_app.py` after changes to app.py**
- **Always use `./deploy.sh` to deploy — never manual `scp` (can corrupt DB)**
- **Never delete `coffee.db` on the Pi — user has real data**
