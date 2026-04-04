## Project Summary

**Coffee Sampler (OptimizeYourCoffee)** — a touchscreen espresso sampling and optimization app for Raspberry Pi.

Solves the problem of systematically tracking espresso shots, evaluating flavors, and dialing in grind settings for home baristas who brew 1-3 shots daily. Replaces pen-and-paper coffee journals with an interactive kiosk.

**Stack:** Python 3 / Flask / SQLite / Chart.js / simple-keyboard. Runs as a Chromium kiosk on Wayland (800x480 DSI touchscreen).

**Entry points:**
- `coffee-app/app.py` — Flask application (~2200 lines), all routes and business logic
- `./deploy.sh` — safe deploy to Raspberry Pi (backs up DB, stops Flask, syncs, restarts)
- `python3 -m pytest tests/test_app.py` — test suite (218 tests)

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
python3 -m pytest tests/test_app.py -v      # full suite (218 tests, ~8s)
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
│   ├── app.py            # ALL routes, models, helpers, migrations (~1440 lines)
│   ├── static/           # CSS, JS modules, Chart.js, data files, icons
│   │   ├── keyboard.js       # Virtual keyboard (wraps simple-keyboard)
│   │   ├── autocomplete.js   # Inline chip autocomplete for form fields
│   │   ├── tastingnotes.js   # Tasting note chip input with emoji lookup
│   │   ├── coffeeinfo.js     # Variety/process info popups
│   │   ├── coffee-info.json  # 18 variety + 16 process descriptions
│   │   └── varieties.json    # ~100 cultivar names for autocomplete
│   └── templates/        # 11 Jinja2 templates (step1-3, edit, stats, insights, settings_notes, settings_grind, settings_taste)
├── reference/            # Domain knowledge docs (tracked in git)
├── notes/                # Process artifacts (gitignored)
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
4. Evaluation saved with UPSERT → diagnostics computed from taste descriptors + brew params → shown immediately
5. Stats page: per-coffee charts from aggregated query data
6. Insights page: cross-coffee groupings (process, origin, roast level) with Chart.js

### Grind aroma prefill
Grind aroma (1-5 score) and grind smell descriptors are captured on the sample page and carried to the evaluation page. They are **not stored on the `samples` table** — only persisted when the user saves the evaluation (to `evaluations.grind_aroma` and `evaluations.aroma_descriptors`).

Prefill priority chain (both sample and eval pages):
1. **Existing evaluation** — when re-editing, the saved values take precedence (template logic)
2. **Query params** — fresh selections from the sample page, passed via URL on redirect
3. **Sticky from last eval** — last evaluation of the same coffee (per-coffee carry-forward)

This means grind aroma "sticks" across shots of the same coffee, while fresh selections from the sample page always override the sticky value on the eval page.

### Database
Single SQLite file (`coffee.db`, WAL mode, foreign keys). 5 tables: `coffees`, `samples`, `evaluations`, `custom_tasting_notes`, `app_settings`. Schema migrations via `ALTER TABLE` in `init_db()` — **never drop/recreate tables** (user has real data).

### Grind optimizer
Three selectable algorithms in Settings → Grind Optimizer, all dispatched via `suggest_grind()`:
- **Best Shots** (`weighted_centroid`): Weighted average of top-scoring shots with time-decay. Default.
- **Smart Curve** (`bayesian_quadratic`): Ridge regression with configurable regularization + optional recency. Pure Python.
- **Classic Curve Fit** (`quadratic`): Standard quadratic regression via numpy. No recency, no regularization.

All share:
- Configurable score source (overall, taste avg, ratio accuracy, single dimension)
- Recipe-matching filter (temp/dose tolerance to exclude shots from different brew setups)
- Cross-coffee prior for sparse data (fallback grind from similar coffees on the same grinder)
- Settings stored in `app_settings` table as JSON via `get_setting()`/`set_setting()`

Preview API (`/api/grind-preview`) runs algorithms on example scenarios in an in-memory SQLite DB.

### State
- **Database** — `~/coffee-app/coffee.db` on Pi (gitignored, backed up to `backups/` on every startup + deploy)
- **Session** — Flask cookie-based (undo state). Secret key in `.secret_key` file.
- **Static data** — `coffee-info.json`, `varieties.json` (checked in, loaded client-side)

### Key design decisions
- **Monolithic app.py** — deliberate for a single-developer kiosk project. At ~2200 lines; consider splitting if it grows past ~2500.
- **Inline chart JS** — server renders JSON into template `<script>` blocks. Avoids extra API calls.
- **Autocomplete as inline chips** (not floating dropdown) — Chromium/Wayland repaint bug prevents `position: fixed` elements toggled via display.
- **`days_since_roast` snapshot on samples** — frozen at creation time, not computed live. Shows bean age when that specific shot was pulled.
- **Grind aroma lives on evaluations, not samples** — captured on the sample page for UX but only persisted to `evaluations` on save. Carried between pages via query params, with sticky prefill from the last eval of the same coffee.
- **Sample↔eval navigation loop** — back arrow on eval goes to edit sample (`?from=eval`), save returns to eval. User escapes via the edit page's back arrow or eval's "Done" button.
- **Timestamped backups** — every Flask startup creates `coffee-YYYY-MM-DD_HHMMSS.db`. Pruned after 60 days.
- **Settings auto-save** — grind optimizer settings page saves on every change via debounced fetch (no save button). Route returns JSON for auto-save (`X-Auto-Save` header), redirect for manual POST.
- **Score-source-dependent UI** — grind settings page swaps algorithm cards based on selected score source. Ratio accuracy shows a dedicated "Directed Search" algorithm; all taste-based sources show the 3 generic algorithms.
- **Diagnostics vs optimizer separation** — `diagnose()` provides observational feedback (what went wrong), grind optimizer provides statistical next-shot suggestions. Diagnostics no longer give grind step advice.

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

### Chromium/Wayland workarounds
- No `display: none` → `display: block` toggling on fixed/absolute elements — use `:empty` CSS collapse
- Autocomplete chips are regular inline DOM, not floating overlays
- `--disk-cache-size=1 --aggressive-cache-discard` on Chromium launch
- Asset cache busting: `?v={{ v }}` where `v` = `CACHE_BUST` (startup timestamp)

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
- **Structure:** `tests/test_app.py` — single file, 218 tests in 34 test classes
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
- Adding a coffee field → must update: schema, migration, `parse_coffee_form()`, `COFFEE_COLUMNS` allowlist, both templates (add + edit), and tests
- Deploying with `scp` instead of `./deploy.sh` → can corrupt the live database
- Using `display: none/block` for dynamic UI → won't work on Chromium/Wayland, use `:empty` or opacity
- Adding a new grind algorithm → must add: algorithm function, dispatch case in `suggest_grind()`, algorithm card in `settings_grind.html`, preview support, tests
- Adding a new score source → must add: entry in `SCORE_SOURCES`, handler in `_extract_score()`, any needed columns in preview API's in-memory schema

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
