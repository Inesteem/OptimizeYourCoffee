# Flask Coffee App Code Review
## Single-Developer Raspberry Pi Kiosk - Architecture & Refactoring Guide

**Date:** 2026-04-02  
**App Size:** 1,110 lines (app.py) + 5 templates + 2 JS files  
**Context:** Single developer, Pi touchscreen kiosk, simplicity over enterprise patterns

---

## Executive Summary: The Good and Bad

**Current State:**
- Functional monolith that works but is hitting maintainability wall
- Strong features: backup system, graceful DB migrations, good UX patterns
- Weak areas: code replication, global state mutation, connection pooling, security edge cases

**Time to Refactor:** ~2-3 hours of focused work across issues
**Urgency:** Medium now (will become critical if adding charts/recipes/ML)

---

## Problem 1: DRY Violation - Add/Edit Form Parsing (40+ Lines)

### Location
- `add_coffee()` lines 535-580
- `save_coffee()` (edit POST) lines 593-643

### What's Happening
```python
# In add_coffee():
best_after = data.get("best_after_days", "").strip()
consume_within = data.get("consume_within_days", "").strip()
bag_weight = data.get("bag_weight_g", "").strip()
bag_price = data.get("bag_price", "").strip()
def_in = data.get("default_grams_in", "").strip()
def_out = data.get("default_grams_out", "").strip()
def_min = data.get("default_brew_min", "").strip()
def_sec = data.get("default_brew_sec", "").strip()
def_time = None
if def_min or def_sec:
    def_time = safe_int(def_min, 0) * 60 + safe_int(def_sec, 0)
# ... 19-parameter INSERT tuple ...

# In save_coffee():
# IDENTICAL code block repeated, same 40 lines
```

### Why It's Bad
1. **Maintenance Tax:** Changing how any field is parsed requires edits in two places
2. **Test Blindness:** Can't easily test parsing logic independently
3. **Future Scaling:** When you add ML grind recommendations, you'll copy-paste this again
4. **Human Error:** Already seen slight divergence (missing `.strip()` calls in some forms)

### The Fix (15 minutes)

Create `coffee_form_utils.py`:
```python
def extract_coffee_form(form_data):
    """Parse and validate coffee form submission."""
    # Time calculation (reusable across add/edit)
    def_time = None
    if form_data.get("default_brew_min") or form_data.get("default_brew_sec"):
        def_time = safe_int(form_data.get("default_brew_min"), 0) * 60 + \
                   safe_int(form_data.get("default_brew_sec"), 0)
    
    return {
        "roaster": form_data.get("roaster", "").strip() or None,
        "origin_country": form_data.get("origin_country", "").strip() or None,
        "origin_city": form_data.get("origin_city", "").strip() or None,
        "origin_producer": form_data.get("origin_producer", "").strip() or None,
        "variety": form_data.get("variety", "").strip() or None,
        "process": form_data.get("process", "").strip() or None,
        "tasting_notes": form_data.get("tasting_notes", "").strip() or None,
        "roast_date": form_data.get("roast_date", "").strip() or None,
        "best_after_days": safe_int(form_data.get("best_after_days", "").strip(), 7),
        "consume_within_days": safe_int(form_data.get("consume_within_days", "").strip(), 50),
        "bag_weight_g": safe_float(form_data.get("bag_weight_g", "").strip()),
        "bag_price": safe_float(form_data.get("bag_price", "").strip()),
        "default_grams_in": safe_float(form_data.get("default_grams_in", "").strip()),
        "default_grams_out": safe_float(form_data.get("default_grams_out", "").strip()),
        "default_brew_time_sec": def_time,
        "bean_color": form_data.get("bean_color", "").strip() or None,
        "bean_size": form_data.get("bean_size", "").strip() or None,
        "opened_date": form_data.get("opened_date", "").strip() or None,
        "label": form_data.get("label", "").strip() or make_label(form_data),
    }
```

Then use it:
```python
@app.route("/coffee", methods=["POST"])
def add_coffee():
    form_data = request.form
    coffee_data = extract_coffee_form(form_data)
    
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO coffees 
               (roaster, origin_country, origin_city, origin_producer, variety, 
                process, tasting_notes, label, roast_date, best_after_days,
                consume_within_days, bag_weight_g, bag_price, default_grams_in,
                default_grams_out, default_brew_time_sec, bean_color, bean_size, opened_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            tuple(coffee_data[key] for key in [
                "roaster", "origin_country", "origin_city", "origin_producer", "variety",
                "process", "tasting_notes", "label", "roast_date", "best_after_days",
                "consume_within_days", "bag_weight_g", "bag_price", "default_grams_in",
                "default_grams_out", "default_brew_time_sec", "bean_color", "bean_size", "opened_date"
            ])
        )
        coffee_id = cur.lastrowid
    return redirect(url_for("new_sample", coffee_id=coffee_id))

@app.route("/coffee/<int:coffee_id>/edit", methods=["POST"])
def save_coffee(coffee_id):
    form_data = request.form
    coffee_data = extract_coffee_form(form_data)
    
    with get_db() as conn:
        conn.execute(
            """UPDATE coffees SET roaster=?, origin_country=?, origin_city=?, 
               origin_producer=?, variety=?, process=?, tasting_notes=?, label=?, 
               roast_date=?, best_after_days=?, consume_within_days=?,
               bag_weight_g=?, bag_price=?, default_grams_in=?, default_grams_out=?, 
               default_brew_time_sec=?, bean_color=?, bean_size=?, opened_date=?,
               updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            tuple(coffee_data[key] for key in [
                "roaster", "origin_country", "origin_city", "origin_producer", "variety",
                "process", "tasting_notes", "label", "roast_date", "best_after_days",
                "consume_within_days", "bag_weight_g", "bag_price", "default_grams_in",
                "default_grams_out", "default_brew_time_sec", "bean_color", "bean_size", "opened_date"
            ]) + (coffee_id,)
        )
    return redirect(url_for("new_sample", coffee_id=coffee_id))
```

**Impact:** Eliminates 40 lines of duplication, makes parsing testable, improves readability.

---

## Problem 2: Global Mutation in render_tasting_notes()

### Location
Lines 244-261 in app.py

### The Code (Problematic Pattern)
```python
TASTING_EMOJIS = { ... }  # Global dict

def render_tasting_notes(notes_str):
    """Convert comma-separated tasting notes to emoji + name pairs."""
    if not notes_str:
        return []
    # MUTATES GLOBAL DICT!
    try:
        with get_db() as conn:
            for row in conn.execute("SELECT name, emoji FROM custom_tasting_notes"):
                key = row["name"].lower().strip()
                if key not in TASTING_EMOJIS and row["emoji"]:
                    TASTING_EMOJIS[key] = row["emoji"]  # <-- SIDE EFFECT
    except Exception:
        pass
    result = []
    for note in notes_str.split(","):
        note = note.strip()
        if note:
            emoji = TASTING_EMOJIS.get(note.lower(), "")
            result.append(f"{emoji} {note}" if emoji else note)
    return result
```

### Why It's Bad
1. **Hidden Side Effect:** A rendering function modifies application state
2. **Caching Impossible:** Can't cache this function's output—it changes on every call
3. **Testing Hell:** Each test might pollute global state for the next
4. **Race Conditions:** If you ever go async/multi-threaded, this breaks spectacularly
5. **Debug Nightmare:** Emoji changes appearing mysteriously without code changes

### The Fix (5 minutes)

Replace global mutation with request-scoped merging:
```python
def get_emoji_map():
    """Get merged emoji map: built-in + custom from DB (no mutation)."""
    emojis = TASTING_EMOJIS.copy()  # Copy, don't mutate!
    try:
        with get_db() as conn:
            for row in conn.execute("SELECT name, emoji FROM custom_tasting_notes"):
                key = row["name"].lower().strip()
                if key not in emojis and row["emoji"]:
                    emojis[key] = row["emoji"]
    except Exception:
        pass
    return emojis

def render_tasting_notes(notes_str):
    """Convert comma-separated tasting notes to emoji + name pairs."""
    if not notes_str:
        return []
    
    emojis = get_emoji_map()  # Local copy, no mutation
    result = []
    for note in notes_str.split(","):
        note = note.strip()
        if note:
            emoji = emojis.get(note.lower(), "")
            result.append(f"{emoji} {note}" if emoji else note)
    return result
```

**Impact:** Eliminates hidden side effects, enables testing, prevents mysterious bugs as app scales.

---

## Problem 3: Emoji Mapping Drift (Python vs JavaScript)

### The Mismatch
| Source | Entry Count | Divergence |
|--------|-------------|-----------|
| `app.py` TASTING_EMOJIS | 48 entries | Missing: "green apple", "peanut", "lavender", "chamomile", "watermelon", "fig", "dates", "cranberry", "cacao", "milk chocolate", "green tea", "earl grey" |
| `tastingnotes.js` NOTES | 60+ entries | Has extras JS doesn't sync back |

### How This Happens
1. Developer adds emoji in JS for front-end UX
2. Forgets to sync to Python's TASTING_EMOJIS
3. Python never learns about custom JS entries
4. Database custom notes silently fail to match

### The Fix (20 minutes, Medium Impact)

**Step 1:** Create `/static/shared_data.json`
```json
{
  "emojis": {
    "dried apricot": "🍑",
    "apricot": "🍑",
    "lemonade": "🍋",
    "lemon": "🍋",
    "orange": "🍊",
    "tangerine": "🍊",
    "black currant": "🫐",
    "blackcurrant": "🫐",
    "blueberry": "🫐",
    "strawberry": "🍓",
    "wild strawberry": "🍓",
    "raspberry": "🍓",
    "raspberry jam": "🍓",
    "cherry": "🍒",
    "apple": "🍏",
    "green apple": "🍏",
    "peach": "🍑",
    "plum": "🍇",
    "grape": "🍇",
    "tropical": "🍍",
    "pineapple": "🍍",
    "mango": "🥭",
    "passionfruit": "🍈",
    "melon": "🍈",
    "watermelon": "🍉",
    "banana": "🍌",
    "fig": "🫐",
    "dates": "🫐",
    "cranberry": "🫐",
    "grapefruit": "🍊",
    "lime": "🍋",
    "citrus": "🍋",
    "bergamot": "🍋",
    "cacao nibs": "🍫",
    "cacao": "🍫",
    "chocolate": "🍫",
    "dark chocolate": "🍫",
    "milk chocolate": "🍫",
    "cocoa": "🍫",
    "hazelnut": "🌰",
    "almond": "🌰",
    "walnut": "🌰",
    "peanut": "🥜",
    "nutty": "🌰",
    "honey": "🍯",
    "caramel": "🍮",
    "toffee": "🍮",
    "brown sugar": "🍮",
    "maple": "🍁",
    "molasses": "🍮",
    "vanilla": "🍦",
    "butterscotch": "🍮",
    "candy": "🍬",
    "sugarcane": "🍬",
    "jasmine": "🌸",
    "rose": "🌹",
    "lavender": "💜",
    "floral": "🌺",
    "hibiscus": "🌺",
    "chamomile": "🌼",
    "tea": "🍵",
    "black tea": "🍵",
    "green tea": "🍵",
    "earl grey": "🍵",
    "herbal": "🌿",
    "mint": "🌿",
    "basil": "🌿",
    "cinnamon": "✨",
    "clove": "✨",
    "cardamom": "✨",
    "ginger": "✨",
    "pepper": "🌶️",
    "spicy": "🌶️",
    "nutmeg": "✨",
    "smoky": "🔥",
    "tobacco": "🍂",
    "wine": "🍷",
    "red wine": "🍷",
    "whiskey": "🥃",
    "rum": "🥃",
    "butter": "🧈",
    "cream": "🥛",
    "yogurt": "🥛",
    "cedar": "🪵",
    "woody": "🪵",
    "earthy": "🌍",
    "stone fruit": "🍑",
    "berry": "🫐",
    "tropical fruit": "🍍",
    "dried fruit": "🍑",
    "nougat": "🍮"
  },
  "processes": [
    "Washed", "Natural", "Honey", "Black Honey", "Red Honey", "Yellow Honey",
    "White Honey", "Anaerobic", "Anaerobic Natural", "Anaerobic Washed",
    "Carbonic Maceration", "Wet Hulled", "Semi-Washed", "Double Washed",
    "Lactic Process", "Swiss Water Decaf"
  ]
}
```

**Step 2:** Load in Python (`app.py`)
```python
import json

def load_shared_data():
    """Load shared config (emojis, processes) from JSON."""
    try:
        with open(Path(__file__).parent / "static" / "shared_data.json") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"emojis": {}, "processes": []}

SHARED_DATA = load_shared_data()
TASTING_EMOJIS = SHARED_DATA.get("emojis", {})
PROCESS_OPTIONS = SHARED_DATA.get("processes", [])

@app.context_processor
def inject_shared_data():
    """Inject process options into all templates."""
    return {"process_options": PROCESS_OPTIONS}
```

**Step 3:** Update templates (e.g., `step1_coffee.html`)
```html
<select id="process" name="process" class="field-select">
    <option value="">— Select —</option>
    {% for p in process_options %}
    <option>{{ p }}</option>
    {% endfor %}
</select>
```

**Step 4:** Update JavaScript (`static/tastingnotes.js`)
```javascript
(function() {
    let NOTES = {};
    let ALL_NOTES = [];

    // Load shared emoji map from server
    fetch('/api/shared-data')
        .then(r => r.json())
        .then(data => {
            NOTES = data.emojis;
            ALL_NOTES = [...new Set(Object.keys(NOTES))].sort();
            // ... rest of code ...
        })
        .catch(err => console.error('Failed to load emoji map:', err));
    
    // ... rest of your code ...
})();
```

**Step 5:** Add Flask route
```python
@app.route("/api/shared-data")
def get_shared_data():
    return jsonify(SHARED_DATA)
```

**Impact:** Single source of truth for emojis and processes, eliminates drift, simplifies template maintenance, enables future data-driven UI.

---

## Problem 4: Hardcoded Process Options in Templates

### Location
- `step1_coffee.html` lines 61-79: 18 `<option>` tags hardcoded inline
- `edit_coffee.html`: Same 18 options in a for loop (different location, same list)
- `app.py` lines 48-52: PROCESS_OPTIONS list exists but not used in templates

### Why It's Bad
1. **Three Places to Update:** Add a new process type? Edit app.py AND both templates
2. **Template Logic:** Templates shouldn't contain domain knowledge
3. **Sync Risk:** Already see divergence (one template in Jinja loop, one hard-coded)
4. **API Confusion:** If you build a mobile app or use a different frontend, where do processes come from?

### The Fix
**Fully covered in Problem 3 above.** The context processor approach solves this completely:

```html
<!-- Before: hardcoded -->
<select id="process" name="process">
    <option value="">— Select —</option>
    <option>Washed</option>
    <option>Natural</option>
    <!-- ... 16 more ... -->
</select>

<!-- After: data-driven -->
<select id="process" name="process">
    <option value="">— Select —</option>
    {% for p in process_options %}
    <option>{{ p }}</option>
    {% endfor %}
</select>
```

**Impact:** Single source of truth, templates become "stupid" (data-driven), scales to recipes, ML models, etc.

---

## Problem 5: Multiple DB Connections Per Request

### Location
`get_db()` function at line 101, called 28 times throughout `app.py`

### The Code (Current)
```python
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
```

### Why It's Bad
1. **Performance:** Each call creates a new connection. On a Pi with limited memory, this causes:
   - 28 connections per request cycle
   - File descriptor exhaustion over time
   - Contention on the SQLite journal
2. **Resource Leak:** If an exception occurs before connection is closed, it stays open
3. **Scalability Blocker:** As you add charts/ML features, you'll hit SQLite limits fast
4. **Concurrency Issues:** Multiple simultaneous requests open overlapping connections = journal contention

### The Fix (10 minutes, Critical Priority)

Use Flask's `g` object for request-scoped connection pooling:

```python
from flask import g

def get_db():
    """Get the database connection for this request (creates once per request)."""
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

@app.teardown_appcontext
def close_connection(exception):
    """Close the database connection at the end of the request."""
    db = g.pop('db', None)
    if db is not None:
        db.close()
```

Now your 28 `get_db()` calls in a single request all return the *same* connection object.

**Impact:** Massive performance and stability improvement. Single connection per request, no resource leaks, enables concurrent users on Pi.

---

## Problem 6: innerHTML XSS Risk (Stored XSS Vulnerability)

### Location
- `autocomplete.js` line 76: `box.innerHTML = matches.map(m => ...)`
- `tastingnotes.js` line 148: `chip.innerHTML = `${emoji ? emoji + ' ' : ''}${note}...`

### The Risk
```javascript
// autocomplete.js (vulnerable)
box.innerHTML = matches.map(m => {
    const idx = m.toLowerCase().indexOf(val);
    const before = m.slice(0, idx);
    const bold = m.slice(idx, idx + val.length);
    const after = m.slice(idx + val.length);
    return `<div class="ac-item" data-value="${m}">
            ${before}<strong>${bold}</strong>${after}
            </div>`;
}).join('');
```

If `m` (from `varieties.json` or DB) contains `<img src=x onerror="alert(1)">`, it executes.

```javascript
// tastingnotes.js (vulnerable)
chip.innerHTML = `${emoji ? emoji + ' ' : ''}${note}<button class="chip-x" data-idx="${idx}">×</button>`;
```

If `note` (user-submitted tasting note) contains HTML, it executes.

### Why It's Bad (In This Context)
- **Stored XSS:** If an attacker (or a bug) injects JavaScript into the database, it runs in every user's browser
- **Trust Boundary:** You're assuming `varieties.json` and user inputs are safe—they're not
- **Escalation Risk:** On a local kiosk with OS access, XSS → RCE via Electron/Chromium

### The Fix (10 minutes, Medium Priority)

Replace `innerHTML` with safe DOM methods:

**autocomplete.js:**
```javascript
// Before (vulnerable)
box.innerHTML = matches.map(m => {
    // ...
    return `<div>...</div>`;
}).join('');

// After (safe)
box.innerHTML = '';  // Clear first
matches.forEach(m => {
    const idx = m.toLowerCase().indexOf(val);
    const before = m.slice(0, idx);
    const bold = m.slice(idx, idx + val.length);
    const after = m.slice(idx + val.length);
    
    const div = document.createElement('div');
    div.className = 'ac-item';
    div.dataset.value = m;  // Safe attribute
    
    // Build content with textContent (never executes HTML)
    const beforeNode = document.createTextNode(before);
    const boldNode = document.createElement('strong');
    boldNode.textContent = bold;  // Safe
    const afterNode = document.createTextNode(after);
    
    div.appendChild(beforeNode);
    div.appendChild(boldNode);
    div.appendChild(afterNode);
    
    box.appendChild(div);
});
```

**tastingnotes.js:**
```javascript
// Before (vulnerable)
chip.innerHTML = `${emoji ? emoji + ' ' : ''}${note}<button class="chip-x" data-idx="${idx}">×</button>`;

// After (safe)
chip.innerHTML = '';  // Clear

// Add emoji + note
const textContent = document.createElement('span');
textContent.textContent = `${emoji ? emoji + ' ' : ''}${note}`;
chip.appendChild(textContent);

// Add delete button
const btn = document.createElement('button');
btn.className = 'chip-x';
btn.dataset.idx = idx;  // Safe attribute
btn.textContent = '×';
btn.addEventListener('click', (e) => {
    e.preventDefault();
    chip.remove();
    // ... update hidden field ...
});
chip.appendChild(btn);
```

**Impact:** Eliminates stored XSS vector, hardening the app against data injection, safe for future features.

---

## Modular Architecture Without Overengineering

### Recommended Structure (For 1,100-Line App)

```
coffee-app/
├── app.py                          # Flask app factory + entry point
├── database.py                     # DB connection, init_db(), backups
├── models.py                       # Coffee, Sample, Evaluation classes (optional but helpful)
├── routes/
│   ├── __init__.py
│   ├── coffee.py                   # add/edit/delete coffee routes
│   ├── sample.py                   # sample creation routes
│   ├── evaluation.py               # evaluation routes
│   ├── stats.py                    # stats/charts routes
│   └── api.py                      # JSON API endpoints (/api/custom-tasting-notes, /api/shared-data)
├── utils.py                        # safe_int, safe_float, coffee_form_utils
├── config.py                       # PROCESS_OPTIONS, constants (or use shared_data.json)
├── static/
│   ├── shared_data.json            # Emojis, processes (shared Python/JS)
│   ├── style.css
│   ├── tastingnotes.js
│   ├── autocomplete.js
│   └── ... other assets ...
└── templates/
    ├── base.html
    ├── step1_coffee.html
    ├── edit_coffee.html
    └── ... others ...
```

### When to Use Blueprints?
Only if routes exceed ~500 lines. Current approach (one file per domain) is good enough.

### When to Add Models?
When you need validation or shared behavior across routes. For now, simpler to keep raw dicts.

---

## 30-Minute Refactoring Roadmap

If you have only 30 minutes, do these in order:

### Tier 1: Critical (Do First)
1. **Fix DB Connection Pooling (10 min)**
   - Implement `flask.g` pattern (Problem 5)
   - This is a blocker for any scaling
   - Immediate performance + stability win

2. **Extract Form Parsing Helper (12 min)**
   - Create `extract_coffee_form()` function (Problem 1)
   - Use in both `add_coffee` and `save_coffee`
   - Eliminates duplication, enables testing

3. **Fix Global Mutation (3 min)**
   - Change `TASTING_EMOJIS.update()` to local copy (Problem 2)
   - Prevents mysterious bugs

### Tier 2: Important (If Time Permits)
4. **Create shared_data.json (10 min)** — Problems 3 & 4
5. **Update templates to use context processor (5 min)**
6. **Fix innerHTML XSS in JS (10 min)** — Problem 6

### Tier 3: Nice-to-Have (Next Session)
7. Split `app.py` into modules
8. Add `/api/shared-data` endpoint for JS to consume emojis
9. Add tests for form parsing

---

## Architectural Patterns for Future Growth

### For Charts
- Don't over-engineer. Use Chart.js (already loaded) with `/api/stats` JSON endpoints
- Example: `/api/stats/best-coffees?days=30` returns aggregated data

### For Recipes
- Same pattern: recipe is just a table with FK to coffee + parameters
- `/api/recipes/<coffee_id>` returns JSON
- Templates render from JS or server-side

### For ML Grind Optimizer
- This is where modularity pays off
- Create `ml/` module with grind prediction logic
- Expose via `/api/grind-recommendation/<coffee_id>` endpoint
- Keeps ML separate from Flask views

---

## Summary Table: Impact vs Effort

| Problem | Fix | Effort | Impact | Do Now? |
|---------|-----|--------|--------|---------|
| DRY Form Parsing | `extract_coffee_form()` | 15 min | High | YES (30-min plan #2) |
| Global Mutation | Use `.copy()` | 3 min | Medium | YES (30-min plan #3) |
| Connection Pooling | `flask.g` | 10 min | Critical | YES (30-min plan #1) |
| Emoji Drift | `shared_data.json` | 20 min | Medium | Next session |
| Hardcoded Processes | Context processor + template loop | 5 min | Medium | Next session |
| innerHTML XSS | Replace with `textContent` + DOM methods | 10 min | Medium | Next session |
| Monolithic app.py | Split into `routes/` + `utils.py` | 30 min | Low | Only if module hits 1500+ lines |

---

## Code Quality Wins Already Present

Before you think everything is bad, note what's working well:

1. **Backup System:** The `backup_db()` function with auto-pruning is solid
2. **DB Migrations:** Graceful ALTER TABLE approach for schema evolution (rare in single-file apps)
3. **UX Patterns:** Chip input, keyboard, autocomplete on a Pi touchscreen is well thought out
4. **Error Handling:** Most DB calls wrapped with context managers
5. **SQL Injection Protection:** Parameterized queries throughout (good)

This is a well-intentioned codebase that just needs some organizational love.

---

## Next Steps

1. **This week:** Do the 30-minute refactoring (Tier 1)
2. **Next week:** Extract `shared_data.json` and fix XSS (Tier 2)
3. **Before adding charts/ML:** Split app.py into modules (Tier 3)

You're in good shape. The groundwork is solid; just needs tidying up before scaling.
