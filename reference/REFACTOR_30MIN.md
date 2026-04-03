# 30-Minute Refactoring Checklist

Complete these three tasks in order. Each is independent and improves the codebase incrementally.

---

## Task 1: Fix DB Connection Pooling (10 minutes)
**File:** `coffee-app/app.py`  
**Current Location:** Lines 101-107

### Replace This:
```python
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
```

### With This:
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

### Why:
- Single connection per request instead of 28 per request
- No resource leaks
- Better concurrency on Pi

### How to Test:
- Run the app normally
- No visible changes, but performance should improve
- Check Pi memory usage (should be lower)

---

## Task 2: Extract Form Parsing Helper (12 minutes)
**File:** `coffee-app/app.py`  
**Affected Functions:** `add_coffee()` (line 535) and `save_coffee()` (line 593)

### Step 1: Create Helper (after line 100, before `get_db()`)
```python
def extract_coffee_form(form_data):
    """Parse and validate coffee form submission. Returns dict ready for DB insert/update."""
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

### Step 2: Replace `add_coffee()` (line 535)
**Replace lines 535-579 with:**
```python
@app.route("/coffee", methods=["POST"])
def add_coffee():
    data = request.form
    coffee_data = extract_coffee_form(data)
    
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO coffees (roaster, origin_country, origin_city, origin_producer,
                                    variety, process, tasting_notes, label, roast_date,
                                    best_after_days, consume_within_days, bag_weight_g, bag_price,
                                    default_grams_in, default_grams_out, default_brew_time_sec,
                                    bean_color, bean_size, opened_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            tuple(coffee_data[k] for k in [
                "roaster", "origin_country", "origin_city", "origin_producer", "variety",
                "process", "tasting_notes", "label", "roast_date", "best_after_days",
                "consume_within_days", "bag_weight_g", "bag_price", "default_grams_in",
                "default_grams_out", "default_brew_time_sec", "bean_color", "bean_size", "opened_date"
            ])
        )
        coffee_id = cur.lastrowid
    return redirect(url_for("new_sample", coffee_id=coffee_id))
```

### Step 3: Replace `save_coffee()` (line 593)
**Replace lines 593-642 with:**
```python
@app.route("/coffee/<int:coffee_id>/edit", methods=["POST"])
def save_coffee(coffee_id):
    data = request.form
    coffee_data = extract_coffee_form(data)
    
    with get_db() as conn:
        conn.execute(
            """UPDATE coffees SET roaster=?, origin_country=?, origin_city=?, origin_producer=?,
                                  variety=?, process=?, tasting_notes=?, label=?, roast_date=?,
                                  best_after_days=?, consume_within_days=?,
                                  bag_weight_g=?, bag_price=?,
                                  default_grams_in=?, default_grams_out=?, default_brew_time_sec=?,
                                  bean_color=?, bean_size=?, opened_date=?,
                                  updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            tuple(coffee_data[k] for k in [
                "roaster", "origin_country", "origin_city", "origin_producer", "variety",
                "process", "tasting_notes", "label", "roast_date", "best_after_days",
                "consume_within_days", "bag_weight_g", "bag_price", "default_grams_in",
                "default_grams_out", "default_brew_time_sec", "bean_color", "bean_size", "opened_date"
            ]) + (coffee_id,)
        )
    return redirect(url_for("new_sample", coffee_id=coffee_id))
```

### Why:
- Eliminates 40 lines of duplicate code
- Changes to parsing logic now happen in one place
- Makes it testable

### How to Test:
- Try adding a coffee (form should work identically)
- Try editing a coffee (form should work identically)
- Check that defaults are applied correctly

---

## Task 3: Fix Global Mutation in render_tasting_notes() (3 minutes)
**File:** `coffee-app/app.py`  
**Current Location:** Lines 244-261

### Replace This Entire Section:
```python
def render_tasting_notes(notes_str):
    """Convert comma-separated tasting notes to emoji + name pairs."""
    if not notes_str:
        return []
    # Merge custom notes from DB
    try:
        with get_db() as conn:
            for row in conn.execute("SELECT name, emoji FROM custom_tasting_notes"):
                key = row["name"].lower().strip()
                if key not in TASTING_EMOJIS and row["emoji"]:
                    TASTING_EMOJIS[key] = row["emoji"]  # <-- MUTATION!
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

### With This:
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

### Why:
- No hidden side effects
- Prevents mysterious bugs where emojis change without code changes
- Makes testing possible

### How to Test:
- Add tasting notes to a coffee
- Edit tasting notes
- Verify emojis display correctly (no change in behavior)

---

## Done!

You've just:
1. Fixed a critical performance bottleneck (DB connections)
2. Eliminated 40 lines of duplication
3. Removed a hidden side effect

**Time spent:** ~25 minutes  
**Result:** More maintainable codebase, better performance on Pi

### Next Session (When You Have Time):
- Problem 3 & 4: Create `shared_data.json` to sync emojis/processes (20 min)
- Problem 6: Fix innerHTML XSS in JavaScript files (10 min)
- Split app.py into modules (only if it grows past 1500 lines)

### How to Verify Nothing Broke:
```bash
cd coffee-app
python -m flask run
# Test adding/editing a coffee
# Test viewing tasting notes
# Check that database saves work
```
