import json
import math
import os
import shutil
import sqlite3
import subprocess
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, jsonify, session

try:
    import numpy as np
except ImportError:
    np = None

DB_PATH = Path(__file__).parent / "coffee.db"
BACKUP_DIR = Path(__file__).parent / "backups"
BACKUP_MAX_DAYS = 60

app = Flask(__name__)


def _get_secret_key():
    """Load or generate a persistent secret key."""
    key_file = Path(__file__).parent / ".secret_key"
    if key_file.exists():
        return key_file.read_bytes()
    key = os.urandom(32)
    key_file.write_bytes(key)
    return key

app.secret_key = os.environ.get("FLASK_SECRET_KEY") or _get_secret_key()

CACHE_BUST = str(int(time.time()))

# Origin map index: country name (lowercase) → SVG filename
_map_index_path = os.path.join(os.path.dirname(__file__), "static", "maps", "origin-map-index.json")
try:
    with open(_map_index_path) as f:
        ORIGIN_MAP_INDEX = json.loads(f.read())
except (FileNotFoundError, json.JSONDecodeError):
    ORIGIN_MAP_INDEX = {}


def safe_int(val, default=None):
    """Parse val as int, returning default if conversion fails."""
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def safe_float(val, default=None):
    """Parse val as float, returning default if conversion fails."""
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def days_since(date_str):
    """Return days between today and a YYYY-MM-DD string, or None on failure."""
    try:
        return (date.today() - datetime.strptime(date_str, "%Y-%m-%d").date()).days
    except (ValueError, TypeError):
        return None


# Column allowlists for undo route (SQL injection prevention)
COFFEE_COLUMNS = {"roaster", "origin_country", "origin_city", "origin_producer",
                  "variety", "process", "tasting_notes", "label", "roast_date",
                  "best_after_days", "consume_within_days", "bag_weight_g", "bag_price",
                  "default_grams_in", "default_grams_out", "default_brew_time_sec",
                  "bean_color", "bean_size", "altitude_min", "altitude_max",
                  "opened_date", "archived", "created_at", "updated_at"}
SAMPLE_COLUMNS = {"coffee_id", "grind_size", "grams_in", "grams_out", "brew_time_sec",
                  "brew_temp_c", "days_since_roast", "days_since_opened", "notes", "created_at"}
EVALUATION_COLUMNS = {"sample_id", "aroma", "acidity", "sweetness", "body", "balance",
                      "overall", "grind_aroma", "aroma_descriptors", "brew_smell_descriptors", "taste_descriptors",
                      "preheat_portafilter", "preheat_cup",
                      "preheat_machine", "eval_notes", "with_milk", "representative", "created_at"}

PROCESS_OPTIONS = [
    "Washed", "Natural", "Honey", "Black Honey", "Red Honey", "Yellow Honey",
    "White Honey", "Anaerobic", "Anaerobic Natural", "Anaerobic Washed",
    "Carbonic Maceration", "Wet Hulled", "Semi-Washed", "Double Washed",
    "Lactic Process", "Swiss Water Decaf",
]

AUTOCOMPLETE_FIELDS = frozenset(["roaster", "origin_country", "origin_city",
                                  "origin_producer", "variety"])

GRIND_SMELL_DESCRIPTORS = [
    "Fruity", "Citrus", "Berry", "Stone fruit",
    "Nutty", "Chocolate", "Cocoa",
    "Floral", "Jasmine",
    "Caramel", "Honey", "Vanilla",
    "Roasted", "Toasted", "Smoky",
    "Green", "Fresh", "Flat", "Faint",
]

BREW_SMELL_DESCRIPTORS = [
    "Fruity", "Citrus", "Berry",
    "Chocolate", "Cocoa", "Nutty",
    "Caramel", "Honey", "Vanilla",
    "Floral", "Roasted", "Smoky",
    "Burned", "Sour", "Acidic",
    "Sweet", "Rich", "Flat",
]

TASTE_DESCRIPTORS = [
    "Fruity", "Citrus", "Berry", "Stone fruit",
    "Nutty", "Chocolate", "Cocoa", "Almond",
    "Caramel", "Honey", "Brown sugar", "Vanilla",
    "Spicy", "Pepper", "Cinnamon",
    "Roasted", "Smoky", "Earthy",
    "Creamy", "Silky", "Clean", "Wine-like",
    "Sour", "Acidic", "Bitter", "Burned", "Ashy",
    "Dry", "Astringent", "Thin", "Watery", "Flat", "Harsh",
]

# =============================================================================
# Sections: backup_db, init_db, helpers, routes (coffee → sample → evaluate →
# stats → settings → API → quit)
# =============================================================================


def backup_db():
    """Create a timestamped backup of coffee.db (+ WAL/SHM) if changed. Prune old backups."""
    BACKUP_DIR.mkdir(exist_ok=True)
    if DB_PATH.exists() and DB_PATH.stat().st_size > 0:
        # Skip backup if DB hasn't been modified since the latest backup
        existing = sorted(BACKUP_DIR.glob("coffee-*.db"))
        skip = False
        if existing:
            latest_backup_mtime = existing[-1].stat().st_mtime
            skip = DB_PATH.stat().st_mtime <= latest_backup_mtime
        if not skip:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            backup_file = BACKUP_DIR / f"coffee-{timestamp}.db"
            try:
                shutil.copy2(DB_PATH, backup_file)
                # WAL mode: also copy journal files for a consistent backup
                for suffix in ("-wal", "-shm"):
                    src = DB_PATH.parent / (DB_PATH.name + suffix)
                    if src.exists():
                        shutil.copy2(src, BACKUP_DIR / (backup_file.name + suffix))
            except OSError:
                pass  # don't crash Flask startup if backup fails
    # Prune old backups (always runs)
    cutoff = datetime.now() - timedelta(days=BACKUP_MAX_DAYS)
    for f in BACKUP_DIR.glob("coffee-*.db"):
        try:
            name = f.stem.replace("coffee-", "")
            fdate = datetime.strptime(name[:10], "%Y-%m-%d")
            if fdate < cutoff:
                f.unlink()
                # Also remove paired WAL/SHM files
                for suffix in ("-wal", "-shm"):
                    paired = f.parent / (f.name + suffix)
                    if paired.exists():
                        paired.unlink()
        except (ValueError, OSError):
            pass


@app.context_processor
def inject_globals():
    """Inject app version, undo state, process options, and descriptor lists into all templates."""
    undo = session.get("undo")
    undo_label = None
    if undo:
        if undo["type"] == "coffee":
            undo_label = f"Deleted coffee: {undo['coffee'].get('label', '?')}"
        elif undo["type"] == "sample":
            undo_label = "Deleted sample"
    return {"v": CACHE_BUST, "undo_label": undo_label, "process_options": PROCESS_OPTIONS,
            "grind_smell_descriptors": GRIND_SMELL_DESCRIPTORS,
            "brew_smell_descriptors": BREW_SMELL_DESCRIPTORS,
            "taste_descriptors": TASTE_DESCRIPTORS}


EVAL_DIMENSIONS = [
    {"key": "aroma", "label": "Aroma", "low": "None", "high": "Complex"},
    {"key": "acidity", "label": "Acidity", "low": "Flat", "high": "Bright"},
    {"key": "sweetness", "label": "Sweetness", "low": "Absent", "high": "Rich"},
    {"key": "body", "label": "Body", "low": "Thin", "high": "Full"},
    {"key": "balance", "label": "Balance", "low": "Poor", "high": "Integrated"},
    {"key": "overall", "label": "Overall", "low": "Bad", "high": "Excellent"},
]


def get_db():
    """Open a SQLite connection with WAL journal mode and foreign keys enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS coffees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                roaster TEXT,
                origin_country TEXT,
                origin_city TEXT,
                origin_producer TEXT,
                variety TEXT,
                process TEXT,
                tasting_notes TEXT,
                label TEXT NOT NULL,
                roast_date TEXT,
                best_after_days INTEGER DEFAULT 7,
                consume_within_days INTEGER DEFAULT 50,
                bag_weight_g REAL,
                bag_price REAL,
                default_grams_in REAL,
                default_grams_out REAL,
                default_brew_time_sec INTEGER,
                bean_color TEXT,
                bean_size TEXT,
                altitude_min INTEGER,
                altitude_max INTEGER,
                opened_date TEXT,
                archived INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # migrate existing DBs
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(coffees)").fetchall()]
        for col, definition in [
            ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
            ("best_after_days", "INTEGER DEFAULT 7"),
            ("consume_within_days", "INTEGER DEFAULT 50"),
            ("bag_weight_g", "REAL"),
            ("bag_price", "REAL"),
            ("default_grams_in", "REAL"),
            ("default_grams_out", "REAL"),
            ("default_brew_time_sec", "INTEGER"),
            ("bean_color", "TEXT"),
            ("bean_size", "TEXT"),
            ("opened_date", "TEXT"),
            ("altitude_min", "INTEGER"),
            ("altitude_max", "INTEGER"),
            ("archived", "INTEGER DEFAULT 0"),
        ]:
            if col not in cols:
                conn.execute(f"ALTER TABLE coffees ADD COLUMN {col} {definition}")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                coffee_id INTEGER NOT NULL REFERENCES coffees(id),
                grind_size REAL NOT NULL,
                grams_in REAL NOT NULL,
                grams_out REAL NOT NULL,
                brew_time_sec INTEGER NOT NULL,
                ratio REAL GENERATED ALWAYS AS (grams_out / NULLIF(grams_in, 0)) STORED,
                brew_temp_c REAL DEFAULT 91,
                days_since_roast INTEGER,
                days_since_opened INTEGER,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # migrate samples
        sample_cols = [r["name"] for r in conn.execute("PRAGMA table_info(samples)").fetchall()]
        if "brew_temp_c" not in sample_cols:
            conn.execute("ALTER TABLE samples ADD COLUMN brew_temp_c REAL DEFAULT 91")
        if "days_since_roast" not in sample_cols:
            conn.execute("ALTER TABLE samples ADD COLUMN days_since_roast INTEGER")
        if "days_since_opened" not in sample_cols:
            conn.execute("ALTER TABLE samples ADD COLUMN days_since_opened INTEGER")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS evaluations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sample_id INTEGER NOT NULL UNIQUE REFERENCES samples(id) ON DELETE CASCADE,
                aroma INTEGER CHECK(aroma BETWEEN 1 AND 5),
                acidity INTEGER CHECK(acidity BETWEEN 1 AND 5),
                sweetness INTEGER CHECK(sweetness BETWEEN 1 AND 5),
                body INTEGER CHECK(body BETWEEN 1 AND 5),
                balance INTEGER CHECK(balance BETWEEN 1 AND 5),
                overall INTEGER CHECK(overall BETWEEN 1 AND 5),
                grind_aroma INTEGER CHECK(grind_aroma BETWEEN 1 AND 5),
                preheat_portafilter INTEGER DEFAULT 1,
                preheat_cup INTEGER DEFAULT 1,
                preheat_machine INTEGER DEFAULT 1,
                aroma_descriptors TEXT,
                brew_smell_descriptors TEXT,
                taste_descriptors TEXT,
                eval_notes TEXT,
                with_milk INTEGER DEFAULT 0,
                representative INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # migrate evaluations
        eval_cols = [r["name"] for r in conn.execute("PRAGMA table_info(evaluations)").fetchall()]
        if "representative" not in eval_cols:
            conn.execute("ALTER TABLE evaluations ADD COLUMN representative INTEGER DEFAULT 0")
        for ecol, edef in [
            ("grind_aroma", "INTEGER"),
            ("preheat_portafilter", "INTEGER DEFAULT 1"),
            ("preheat_cup", "INTEGER DEFAULT 1"),
            ("preheat_machine", "INTEGER DEFAULT 1"),
            ("aroma_descriptors", "TEXT"),
            ("brew_smell_descriptors", "TEXT"),
            ("taste_descriptors", "TEXT"),
            ("eval_notes", "TEXT"),
            ("with_milk", "INTEGER DEFAULT 0"),
        ]:
            if ecol not in eval_cols:
                conn.execute(f"ALTER TABLE evaluations ADD COLUMN {ecol} {edef}")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS custom_tasting_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                emoji TEXT DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)


def get_setting(conn, key, default=None):
    """Read a setting from app_settings, returning default if missing."""
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn, key, value):
    """Upsert a setting in app_settings."""
    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?",
        (key, value, value),
    )


# IMPORTANT: This dict must stay in sync with the NOTES object in
# static/tastingnotes.js. Future: generate one from the other via shared JSON.
TASTING_EMOJIS = {
    # Fruits
    "dried apricot": "🍑", "apricot": "🍑", "lemonade": "🍋", "lemon": "🍋",
    "orange": "🍊", "tangerine": "🍊", "black currant": "🫐", "blackcurrant": "🫐",
    "blueberry": "🫐", "strawberry": "🍓", "wild strawberry": "🍓",
    "raspberry": "🍓", "raspberry jam": "🍓", "cherry": "🍒",
    "apple": "🍏", "green apple": "🍏", "peach": "🍑",
    "plum": "🍇", "grape": "🍇", "tropical": "🍍", "pineapple": "🍍",
    "mango": "🥭", "passionfruit": "🍈", "melon": "🍈", "watermelon": "🍉",
    "banana": "🍌", "fig": "🫐", "dates": "🫐", "cranberry": "🫐",
    "grapefruit": "🍊", "lime": "🍋", "citrus": "🍋", "bergamot": "🍋",
    # Chocolate & nuts
    "cacao nibs": "🍫", "cacao": "🍫", "chocolate": "🍫",
    "dark chocolate": "🍫", "milk chocolate": "🍫", "cocoa": "🍫",
    "hazelnut": "🌰", "almond": "🌰", "walnut": "🌰", "peanut": "🥜",
    "nutty": "🌰",
    # Sweet
    "honey": "🍯", "caramel": "🍮", "toffee": "🍮", "brown sugar": "🍮",
    "maple": "🍁", "molasses": "🍮", "vanilla": "🍦", "butterscotch": "🍮",
    "candy": "🍬", "sugarcane": "🍬",
    # Floral & herbal
    "jasmine": "🌸", "rose": "🌹", "lavender": "💜", "floral": "🌺",
    "hibiscus": "🌺", "chamomile": "🌼", "tea": "🍵", "black tea": "🍵",
    "green tea": "🍵", "earl grey": "🍵", "herbal": "🌿", "mint": "🌿",
    "basil": "🌿",
    # Spice
    "cinnamon": "✨", "clove": "✨", "cardamom": "✨", "ginger": "✨",
    "pepper": "🌶️", "spicy": "🌶️", "nutmeg": "✨",
    # Other
    "smoky": "🔥", "tobacco": "🍂", "wine": "🍷", "red wine": "🍷",
    "whiskey": "🥃", "rum": "🥃", "butter": "🧈", "cream": "🥛",
    "yogurt": "🥛", "cedar": "🪵", "woody": "🪵", "earthy": "🌍",
    "berry": "🫐", "stone fruit": "🍑", "tropical fruit": "🍍",
    "dried fruit": "🍑", "nougat": "🍮",
}


def render_tasting_notes(notes_str):
    """Convert comma-separated tasting notes to emoji + name display strings."""
    if not notes_str:
        return []
    merged = dict(TASTING_EMOJIS)
    try:
        with get_db() as conn:
            for row in conn.execute("SELECT name, emoji FROM custom_tasting_notes"):
                key = row["name"].lower().strip()
                if row["emoji"]:
                    merged[key] = row["emoji"]
    except Exception:
        pass
    result = []
    for note in notes_str.split(","):
        note = note.strip()
        if note:
            emoji = merged.get(note.lower(), "")
            result.append(f"{emoji} {note}" if emoji else note)
    return result


def make_label(data):
    """Build a display label from roaster, variety, and process (e.g. 'Roaster - Variety - Process')."""
    parts = [data.get("roaster", ""), data.get("variety", ""), data.get("process", "")]
    label = " - ".join(p.strip() for p in parts if p and p.strip())
    return label or "Unnamed Coffee"


# Roast-level-dependent freshness windows.
# Default (no bean_color) assumes espresso roast (Medium-Dark).
# Keys: (degas_days, best_after, peak_duration, good_duration, consume_within)
FRESHNESS_WINDOWS = {
    "Light":       (4, 12, 14, 14, 60),
    "Medium-Light": (3, 10, 13, 14, 55),
    "Medium":      (3, 7, 11, 14, 50),
    "Medium-Dark": (2, 5,  9, 12, 42),
    "Dark":        (2, 4,  8, 10, 35),
}
FRESHNESS_DEFAULT = FRESHNESS_WINDOWS["Medium-Dark"]  # espresso roast assumption


def freshness_status(coffee):
    """Compute freshness status from roast_date, bean_color, best_after_days,
    consume_within_days, and opened_date.

    Roast-level-dependent windows (darker roasts degrade faster).
    Opened-date acceleration (open bags degrade faster).

    Stages:
    - Degassing: high CO2, shots unstable/sour
    - Resting: CO2 releasing, flavor developing
    - Peak: origin character vibrant, crema rich
    - Good: some volatiles fading, still pleasant
    - Fading: noticeably flat, papery notes emerging
    - Stale: cardboard/musty, not recommended
    """
    if not coffee["roast_date"]:
        return None
    try:
        roast = datetime.strptime(coffee["roast_date"], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None

    days = (date.today() - roast).days

    # Roast-level windows (user overrides take precedence)
    try:
        bean_color = coffee["bean_color"]
    except (KeyError, IndexError):
        bean_color = None
    window = FRESHNESS_WINDOWS.get(bean_color, FRESHNESS_DEFAULT)
    degas_days, default_best_after, peak_dur, good_dur, default_consume = window

    best_after = coffee["best_after_days"] or default_best_after
    consume_within = coffee["consume_within_days"] or default_consume

    # Opened-date acceleration: open bags degrade faster
    open_penalty = 0
    days_open = None
    try:
        opened = coffee["opened_date"]
    except (KeyError, IndexError):
        opened = None
    if opened:
        try:
            open_date = datetime.strptime(opened, "%Y-%m-%d").date()
            days_open = (date.today() - open_date).days
            if days_open > 21:
                open_penalty = 20
            elif days_open > 14:
                open_penalty = 12
            elif days_open > 7:
                open_penalty = 5
        except (ValueError, TypeError):
            pass

    effective_days = days + open_penalty

    # Stage boundaries
    degas_end = min(degas_days, best_after)
    rest_end = best_after
    peak_end = min(best_after + peak_dur, consume_within)
    good_end = min(best_after + peak_dur + good_dur, consume_within)
    fading_end = consume_within

    open_note = ""
    if open_penalty > 0 and days_open is not None:
        open_note = f" (open {days_open}d — aging faster)"

    if days < 0:
        return {"stage": "not roasted yet", "css": "fresh-future", "days": days,
                "detail": f"Roast date is {-days} days from now"}
    elif effective_days < degas_end:
        return {"stage": "degassing", "css": "fresh-degas", "days": days,
                "detail": f"High CO2 — shots will be sour and unstable (day {days})"}
    elif effective_days < rest_end:
        remaining = rest_end - effective_days
        return {"stage": "resting", "css": "fresh-rest", "days": days,
                "detail": f"Almost ready — {remaining} more day{'s' if remaining != 1 else ''} to go{open_note}"}
    elif effective_days <= peak_end:
        return {"stage": "peak", "css": "fresh-peak", "days": days,
                "detail": f"Peak flavor window (day {days}){open_note}"}
    elif effective_days <= good_end:
        remaining = good_end - effective_days
        return {"stage": "good", "css": "fresh-good", "days": days,
                "detail": f"Still great — {remaining} days of prime left{open_note}"}
    elif effective_days <= fading_end:
        remaining = fading_end - effective_days
        return {"stage": "fading", "css": "fresh-fading", "days": days,
                "detail": f"Fading — use within {remaining} days{open_note}"}
    else:
        over = effective_days - fading_end
        return {"stage": "stale", "css": "fresh-stale", "days": days,
                "detail": f"Past prime by {over} day{'s' if over != 1 else ''}{open_note}"}


def diagnose(ev, taste_desc=None, actual_out=None, target_out=None, brew_time=None):
    """Return diagnostic tips based on scores and taste descriptors.

    Focuses on identifying extraction problems and puck prep issues.
    Grind size adjustment suggestions are handled by the grind optimizer
    (Settings → Grind Optimizer).
    """
    tips = []
    acidity = ev.get("acidity") or 3
    sweetness = ev.get("sweetness") or 3
    body = ev.get("body") or 3
    taste_tags = set(t.strip().lower() for t in (taste_desc or "").split(",") if t.strip())

    # Taste descriptor-based diagnostics (work even with 0 prior shots)
    under_signs = taste_tags & {"sour", "acidic", "thin", "watery", "flat"}
    over_signs = taste_tags & {"bitter", "burned", "ashy", "dry", "astringent", "harsh"}

    if under_signs and over_signs:
        tips.append("Sour AND bitter — likely channeling. Fix puck prep first: use WDT, distribute evenly, tamp consistently.")
    elif len(under_signs) >= 3 or (len(under_signs) >= 2 and acidity >= 4):
        tips.append(f"Strongly under-extracted ({', '.join(under_signs)}).")
    elif under_signs:
        tips.append(f"Signs of under-extraction ({', '.join(under_signs)}).")
    elif len(over_signs) >= 3 or (len(over_signs) >= 2 and sweetness <= 2):
        tips.append(f"Strongly over-extracted ({', '.join(over_signs)}).")
    elif over_signs:
        tips.append(f"Signs of over-extraction ({', '.join(over_signs)}).")

    # Score-based diagnostics (fallback when no taste descriptors selected)
    if not tips:
        if acidity >= 4 and sweetness <= 2 and body <= 2:
            tips.append("Likely under-extracted — high acidity, low sweetness, thin body.")
        elif acidity >= 4 and sweetness <= 2:
            tips.append("High acidity with low sweetness — likely slightly under-extracted.")
        elif acidity <= 2 and sweetness <= 2:
            tips.append("Low acidity and low sweetness — likely over-extracted.")
        elif body <= 2 and sweetness >= 3:
            tips.append("Thin body despite decent sweetness — consider increasing dose.")

    # Brew time observation (informational, no grind advice)
    if brew_time:
        if brew_time < 20:
            tips.append(f"Very fast shot ({brew_time}s) — target is 25-30s.")
        elif brew_time > 35:
            tips.append(f"Very slow shot ({brew_time}s) — target is 25-30s. Check for choke.")

    # Output deviation observation (informational, no grind advice)
    if actual_out and target_out and target_out > 0:
        dev_g = actual_out - target_out
        if abs(dev_g) > 5:
            direction = "over" if dev_g > 0 else "under"
            tips.append(f"Output {abs(dev_g):.0f}g {direction} target ({actual_out:.0f}g vs {target_out:.0f}g).")

    # Positive feedback
    if (ev.get("balance") or 3) >= 4 and (ev.get("overall") or 3) >= 4:
        tips.append("Great shot! Save this recipe as a reference.")
    elif not tips:
        if (ev.get("overall") or 3) >= 4:
            tips.append("Solid shot. Minor tweaks could make it even better.")

    return tips


TASTE_PREF_DEFAULTS = {"sweetness": 3, "acidity": 3, "body": 3, "aroma": 3}
TASTE_PREF_DIMS = ["sweetness", "acidity", "body", "aroma"]


def _taste_preferences(conn):
    """Load user taste preferences (1-5 per dimension, 3 = neutral)."""
    raw = get_setting(conn, "taste_preferences", None)
    prefs = json.loads(raw) if raw else {}
    return {d: max(1, min(5, int(prefs.get(d, TASTE_PREF_DEFAULTS[d])))) for d in TASTE_PREF_DIMS}


def coffee_rating(coffee_id, conn):
    """Compute aggregate rating from representative evaluated shots for a coffee."""
    rows = conn.execute(
        """SELECT e.aroma, e.acidity, e.sweetness, e.body, e.balance, e.overall
           FROM evaluations e JOIN samples s ON e.sample_id = s.id
           WHERE s.coffee_id = ? AND e.representative = 1
             AND e.aroma IS NOT NULL AND e.overall IS NOT NULL""",
        (coffee_id,),
    ).fetchall()

    if not rows:
        return None

    dims = ["aroma", "acidity", "sweetness", "body", "balance"]
    totals = {d: 0 for d in dims}
    overall_sum = 0
    for r in rows:
        for d in dims:
            totals[d] += r[d] or 3
        overall_sum += r["overall"] or 3
    n = len(rows)
    avgs = {d: totals[d] / n for d in dims}
    avg_overall = overall_sum / n

    # Quality score: balance + overall (2x) are always included.
    # Other dimensions contribute based on user taste preferences:
    #   preference 5 → weight +1 (high scores boost quality)
    #   preference 3 → weight  0 (neutral, ignored)
    #   preference 1 → weight -1 (high scores hurt quality)
    # The 2×overall anchoring keeps quality stable for realistic preferences
    # (1-2 adjusted dimensions). Extreme edge cases (all 4 set to "dislike")
    # can hit the clamp at 1.0, but in practice a user who dislikes a dimension
    # will already rate such coffees low in their overall score.
    prefs = _taste_preferences(conn)
    num = avgs["balance"] + 2 * avg_overall
    den = 3.0  # base: balance(1) + overall(2)
    for d in TASTE_PREF_DIMS:
        w = (prefs[d] - 3) / 2.0  # -1 to +1
        if abs(w) > 0.01:
            num += w * avgs[d]
            den += abs(w)
    quality = max(1.0, min(5.0, num / den)) if den > 0 else avg_overall

    # Flavor profile descriptor — acidity, body, aroma describe the character
    descriptors = []
    if avgs["acidity"] >= 3.5:
        descriptors.append("Bright")
    elif avgs["acidity"] <= 2:
        descriptors.append("Mellow")
    if avgs["body"] >= 3.5:
        descriptors.append("Full-bodied")
    elif avgs["body"] <= 2:
        descriptors.append("Light")
    if avgs["aroma"] >= 4:
        descriptors.append("Aromatic")

    # Rating tier based on quality score
    if quality >= 4.5:
        tier = "Outstanding"
        css = "tier-outstanding"
    elif quality >= 3.8:
        tier = "Excellent"
        css = "tier-excellent"
    elif quality >= 3.0:
        tier = "Very Good"
        css = "tier-verygood"
    elif quality >= 2.2:
        tier = "Good"
        css = "tier-good"
    else:
        tier = "Below Average"
        css = "tier-below"

    profile = ", ".join(descriptors) if descriptors else "Neutral profile"

    return {
        "tier": tier,
        "css": css,
        "quality": round(quality, 1),
        "avg_overall": round(avg_overall, 1),
        "profile": profile,
        "avgs": {d: round(avgs[d], 1) for d in dims},
        "n": n,
    }


SCORE_SOURCES = {
    "overall": "Overall score",
    "taste_avg": "Taste average (5 dimensions)",
    "ratio_accuracy": "Ratio accuracy (hit target output)",
    "sweetness": "Sweetness",
    "acidity": "Acidity",
    "body": "Body",
    "balance": "Balance",
    "aroma": "Aroma",
}

GRIND_FILTER_DEFAULTS = {
    "score_source": "overall",
    "match_recipe": False,
    "temp_tolerance": 2.0,
    "dose_tolerance": 1.0,
    "finer_is_lower": True,
}


def suggest_grind(coffee_id, conn):
    """Dispatch to the selected grind suggestion algorithm."""
    filt = _grind_filter_params(conn)
    if filt["score_source"] == "ratio_accuracy":
        return _suggest_grind_ratio(coffee_id, conn)
    algo = get_setting(conn, "grind_algorithm", "weighted_centroid")
    if algo == "quadratic":
        return _suggest_grind_quadratic(coffee_id, conn)
    elif algo == "bayesian_quadratic":
        return _suggest_grind_bayesian(coffee_id, conn)
    else:
        return _suggest_grind_centroid(coffee_id, conn)


def _grind_filter_params(conn):
    """Load grind filter settings."""
    raw = get_setting(conn, "grind_filter_params", None)
    params = json.loads(raw) if raw else {}
    return {k: params.get(k, v) for k, v in GRIND_FILTER_DEFAULTS.items()}


def _apply_recipe_filter(rows, filt):
    """Filter rows to those matching the latest shot's temp/dose within tolerance."""
    if not filt["match_recipe"] or len(rows) <= 1:
        return rows
    latest = rows[-1]
    ref_temp = latest["brew_temp_c"]
    ref_dose = latest["grams_in"]
    temp_tol = float(filt["temp_tolerance"])
    dose_tol = float(filt["dose_tolerance"])
    filtered = []
    for r in rows:
        if ref_temp is not None and r["brew_temp_c"] is not None:
            if abs(r["brew_temp_c"] - ref_temp) > temp_tol:
                continue
        if ref_dose is not None and r["grams_in"] is not None:
            if abs(r["grams_in"] - ref_dose) > dose_tol:
                continue
        filtered.append(r)
    return filtered if filtered else rows


def _extract_score(row, score_source, target_out=None):
    """Extract the score value from a row based on the configured source."""
    if score_source == "taste_avg":
        dims = [row["aroma"], row["acidity"], row["sweetness"], row["body"], row["balance"]]
        valid = [d for d in dims if d is not None]
        return round(sum(valid) / len(valid), 1) if valid else None
    elif score_source == "ratio_accuracy":
        try:
            actual = row["grams_out"]
        except (KeyError, IndexError):
            actual = None
        if actual is None or target_out is None or target_out <= 0:
            return None
        dev = abs(actual - target_out)
        if dev <= 1:
            return 5.0
        elif dev <= 2:
            return 4.0
        elif dev <= 4:
            return 3.0
        elif dev <= 7:
            return 2.0
        else:
            return 1.0
    elif score_source in ("sweetness", "acidity", "body", "balance", "aroma"):
        return row[score_source]
    else:
        return row["overall"]


def _grind_rows(coffee_id, conn):
    """Fetch evaluated shots with brew params for grind algorithms.

    Applies recipe-matching filter (temp/dose tolerance) and extracts
    the configured score source.
    """
    filt = _grind_filter_params(conn)
    score_source = filt["score_source"]

    # For ratio_accuracy, we need the coffee's target output
    target_out = None
    if score_source == "ratio_accuracy":
        coffee = conn.execute(
            "SELECT default_grams_out FROM coffees WHERE id = ?", (coffee_id,)
        ).fetchone()
        target_out = coffee["default_grams_out"] if coffee else None

    all_rows = conn.execute(
        """SELECT s.grind_size, s.grams_in, s.grams_out, s.brew_time_sec,
                  s.brew_temp_c, s.created_at,
                  e.overall, e.aroma, e.acidity, e.sweetness, e.body, e.balance
           FROM samples s JOIN evaluations e ON e.sample_id = s.id
           WHERE s.coffee_id = ? AND e.overall IS NOT NULL
           ORDER BY s.created_at""",
        (coffee_id,),
    ).fetchall()

    if not all_rows:
        return []

    all_rows = _apply_recipe_filter(all_rows, filt)

    # Build result rows with extracted score
    result = []
    for r in all_rows:
        score = _extract_score(r, score_source, target_out=target_out)
        if score is not None and r["grind_size"] is not None:
            result.append({
                "grind_size": r["grind_size"],
                "score": score,
                "overall": r["overall"],
                "grams_in": r["grams_in"],
                "grams_out": r["grams_out"],
                "brew_time_sec": r["brew_time_sec"],
                "brew_temp_c": r["brew_temp_c"],
                "created_at": r["created_at"],
            })
    return result


def _time_weights(rows, decay_rate):
    """Compute exponential time-decay weights for rows. Recent shots weigh more."""
    now = datetime.now()
    weights = []
    for r in rows:
        try:
            created = datetime.strptime(r["created_at"][:19], "%Y-%m-%d %H:%M:%S")
            days_ago = max((now - created).total_seconds() / 86400, 0)
        except (ValueError, TypeError):
            days_ago = 365  # unknown timestamp gets minimal weight
        weights.append(math.exp(-decay_rate * days_ago))
    return weights


def _cross_coffee_prior(coffee_id, conn):
    """Compute a grind starting point from similar coffees on the same grinder.

    Fallback chain:
    1. Same process + same bean color (roast level)
    2. Same process only
    3. Same bean color only
    4. All coffees with evaluated shots

    Returns dict with grind, match description, and count, or None.
    """
    coffee = conn.execute(
        "SELECT process, bean_color FROM coffees WHERE id = ?", (coffee_id,)
    ).fetchone()
    if not coffee:
        return None

    process = coffee["process"]
    bean_color = coffee["bean_color"]

    # Try each level of the fallback chain
    levels = []
    if process and bean_color:
        levels.append((
            "AND c.process = ? AND c.bean_color = ?",
            [process, bean_color],
            f"{process} {bean_color} coffees",
        ))
    if process:
        levels.append((
            "AND c.process = ?",
            [process],
            f"{process} coffees",
        ))
    if bean_color:
        levels.append((
            "AND c.bean_color = ?",
            [bean_color],
            f"{bean_color} coffees",
        ))
    levels.append(("", [], "all your coffees"))

    for where_extra, params, match_desc in levels:
        rows = conn.execute(f"""
            SELECT AVG(s.grind_size) as avg_grind, COUNT(DISTINCT c.id) as n_coffees,
                   COUNT(*) as n_shots
            FROM samples s
            JOIN evaluations e ON e.sample_id = s.id
            JOIN coffees c ON s.coffee_id = c.id
            WHERE s.coffee_id != ? AND e.overall IS NOT NULL {where_extra}
        """, [coffee_id] + params).fetchone()

        if rows and rows["n_shots"] >= 3 and rows["n_coffees"] >= 1:
            return {
                "grind": round(rows["avg_grind"], 1),
                "match": match_desc,
                "n_coffees": rows["n_coffees"],
                "n_shots": rows["n_shots"],
            }

    return None


def _low_data_fallback(rows, coffee_id=None, conn=None):
    """Fallback for sparse data: use cross-coffee prior or best shot."""
    # Try cross-coffee prior when we have a DB connection
    prior = _cross_coffee_prior(coffee_id, conn) if coffee_id and conn else None

    if rows:
        best = max(rows, key=lambda r: r["score"])
        detail = f"Best so far: grind {best['grind_size']} scored {best['score']}/5 ({len(rows)} shot{'s' if len(rows) != 1 else ''} evaluated)"
        if prior:
            detail += f". Your {prior['match']} average grind {prior['grind']} ({prior['n_coffees']} coffee{'s' if prior['n_coffees'] != 1 else ''}, {prior['n_shots']} shots)"
        return {
            "grind": best["grind_size"],
            "confidence": "low",
            "detail": detail,
        }

    # No shots at all for this coffee — use prior as the suggestion
    if prior:
        return {
            "grind": prior["grind"],
            "confidence": "low",
            "detail": f"No shots yet. Your {prior['match']} average grind {prior['grind']} ({prior['n_coffees']} coffee{'s' if prior['n_coffees'] != 1 else ''}, {prior['n_shots']} shots) — try starting there",
        }
    return None


# --- Algorithm 1: Quadratic Regression (original) ---

def _suggest_grind_quadratic(coffee_id, conn):
    """Quadratic regression on (grind, score) via numpy.polyfit."""
    rows = _grind_rows(coffee_id, conn)

    if len(rows) < 3:
        return _low_data_fallback(rows, coffee_id, conn)

    if np is None:
        best = max(rows, key=lambda r: r["score"])
        return {"grind": best["grind_size"], "confidence": "low",
                "detail": f"Best so far: grind {best['grind_size']} ({best['score']}/5) — curve fit unavailable, install numpy for this algorithm"}

    grinds = np.array([r["grind_size"] for r in rows], dtype=float)
    scores = np.array([r["score"] for r in rows], dtype=float)

    try:
        coeffs = np.polyfit(grinds, scores, 2)
    except (np.linalg.LinAlgError, ValueError):
        best = max(rows, key=lambda r: r["score"])
        return {"grind": best["grind_size"], "confidence": "low",
                "detail": f"Best so far: grind {best['grind_size']} scored {best['score']}/5"}

    a, b, c = coeffs
    if a >= 0:
        best = max(rows, key=lambda r: r["score"])
        return {"grind": best["grind_size"], "confidence": "low",
                "detail": f"No clear pattern yet — best shot at grind {best['grind_size']} ({best['score']}/5)"}

    optimal = -b / (2 * a)
    gmin, gmax = float(grinds.min()), float(grinds.max())

    if optimal < gmin - 5 or optimal > gmax + 5:
        direction = "finer" if optimal < gmin else "coarser"
        return {"grind": round(optimal, 1), "confidence": "low",
                "detail": f"Peak is outside your range — try going {direction} (grind ~{optimal:.1f})."}

    n = len(rows)
    conf = "medium" if n < 6 else "high"
    best_actual = max(rows, key=lambda r: r["score"])
    return {
        "grind": round(optimal, 1), "confidence": conf,
        "detail": f"Curve fit from {n} shots. Your best shot scored {best_actual['score']}/5 at grind {best_actual['grind_size']}.",
    }


# --- Algorithm 2: Weighted Centroid (Gemini) ---

CENTROID_DEFAULTS = {"decay_rate": 0.05, "top_n": 3, "score_weight_power": 2.0}

def _suggest_grind_centroid(coffee_id, conn):
    """Weighted centroid of top-scoring shots with time-decay.

    Selects top_n shots by overall score, weights each by
    score^power * exp(-decay_rate * days_ago), then computes
    the weighted average grind setting.
    """
    rows = _grind_rows(coffee_id, conn)
    if len(rows) < 2:
        return _low_data_fallback(rows, coffee_id, conn)

    # Load tunable params
    params_json = get_setting(conn, "grind_centroid_params", None)
    params = json.loads(params_json) if params_json else {}
    decay_rate = float(params.get("decay_rate", CENTROID_DEFAULTS["decay_rate"]))
    top_n = int(params.get("top_n", CENTROID_DEFAULTS["top_n"]))
    score_power = float(params.get("score_weight_power", CENTROID_DEFAULTS["score_weight_power"]))

    time_w = _time_weights(rows, decay_rate)

    # Combine score and time into a ranking weight
    ranked = []
    for i, r in enumerate(rows):
        score = r["score"]
        w = (score ** score_power) * time_w[i]
        ranked.append((r["grind_size"], score, w))

    # Sort by combined weight descending, take top_n
    ranked.sort(key=lambda x: x[2], reverse=True)
    top = ranked[:max(top_n, 1)]

    total_w = sum(t[2] for t in top)
    if total_w == 0:
        return _low_data_fallback(rows, coffee_id, conn)

    weighted_grind = sum(t[0] * t[2] for t in top) / total_w

    n = len(rows)
    conf = "low" if n < 3 else ("medium" if n < 6 else "high")
    best_actual = max(rows, key=lambda r: r["score"])

    return {
        "grind": round(weighted_grind, 1),
        "confidence": conf,
        "detail": f"Based on your top {len(top)} of {n} shots. Your best shot scored {best_actual['score']}/5 at grind {best_actual['grind_size']}.",
    }


# --- Algorithm 3: Bayesian Quadratic (Perplexity) ---

BAYESIAN_DEFAULTS = {"prior_strength": 1.0, "decay_rate": 0.05, "use_recency": True}

def _suggest_grind_bayesian(coffee_id, conn):
    """Quadratic regression with L2 regularization (ridge) and optional time-decay.

    Adds a prior that shrinks quadratic coefficients toward zero,
    preventing wild extrapolation with sparse data. Optionally
    applies recency weighting so recent shots count more.
    """
    rows = _grind_rows(coffee_id, conn)
    if len(rows) < 3:
        return _low_data_fallback(rows, coffee_id, conn)

    # Load tunable params
    params_json = get_setting(conn, "grind_bayesian_params", None)
    params = json.loads(params_json) if params_json else {}
    prior_strength = float(params.get("prior_strength", BAYESIAN_DEFAULTS["prior_strength"]))
    decay_rate = float(params.get("decay_rate", BAYESIAN_DEFAULTS["decay_rate"]))
    use_recency = params.get("use_recency", BAYESIAN_DEFAULTS["use_recency"])

    grinds = [r["grind_size"] for r in rows]
    scores = [r["score"] for r in rows]
    weights = _time_weights(rows, decay_rate) if use_recency else [1.0] * len(rows)

    # Weighted ridge regression: minimize sum(w_i * (y_i - f(x_i))^2) + λ * (a^2 + b^2)
    # Normal equations: (X^T W X + λI) β = X^T W y
    n = len(grinds)
    # Build design matrix [x^2, x, 1]
    X = [[g**2, g, 1.0] for g in grinds]

    # X^T W X  (3x3)
    lam = prior_strength
    XtWX = [[0.0]*3 for _ in range(3)]
    XtWy = [0.0]*3
    for i in range(n):
        w = weights[i]
        for j in range(3):
            for k in range(3):
                XtWX[j][k] += w * X[i][j] * X[i][k]
            XtWy[j] += w * X[i][j] * scores[i]

    # Add L2 penalty to quadratic and linear terms (not intercept)
    XtWX[0][0] += lam
    XtWX[1][1] += lam

    # Solve 3x3 system via Cramer's rule
    def det3(m):
        return (m[0][0]*(m[1][1]*m[2][2]-m[1][2]*m[2][1])
               -m[0][1]*(m[1][0]*m[2][2]-m[1][2]*m[2][0])
               +m[0][2]*(m[1][0]*m[2][1]-m[1][1]*m[2][0]))

    D = det3(XtWX)
    if abs(D) < 1e-12:
        best = max(rows, key=lambda r: r["score"])
        return {"grind": best["grind_size"], "confidence": "low",
                "detail": f"Best so far: grind {best['grind_size']} scored {best['score']}/5"}

    def replace_col(mat, col, vec):
        m = [row[:] for row in mat]
        for i in range(3):
            m[i][col] = vec[i]
        return m

    a = det3(replace_col(XtWX, 0, XtWy)) / D
    b = det3(replace_col(XtWX, 1, XtWy)) / D
    c = det3(replace_col(XtWX, 2, XtWy)) / D

    if a >= 0:
        best = max(rows, key=lambda r: r["score"])
        return {"grind": best["grind_size"], "confidence": "low",
                "detail": f"No clear pattern yet — best shot at grind {best['grind_size']} ({best['score']}/5)"}

    optimal = -b / (2 * a)
    gmin, gmax = min(grinds), max(grinds)

    if optimal < gmin - 5 or optimal > gmax + 5:
        direction = "finer" if optimal < gmin else "coarser"
        return {"grind": round(optimal, 1), "confidence": "low",
                "detail": f"Peak is outside your range — try going {direction} (grind ~{optimal:.1f})."}

    conf = "medium" if n < 6 else "high"
    best_actual = max(rows, key=lambda r: r["score"])
    recency_tag = ", recency-weighted" if use_recency else ""
    return {
        "grind": round(optimal, 1), "confidence": conf,
        "detail": f"Cautious curve fit from {n} shots{recency_tag}. Your best shot scored {best_actual['score']}/5 at grind {best_actual['grind_size']}.",
    }


# --- Algorithm 4: Ratio-Directed Search ---

DEFAULT_GRIND_SENSITIVITY = 2.0  # grams output change per grind step (fallback)

def _suggest_grind_ratio(coffee_id, conn):
    """Directed grind search for ratio accuracy optimization.

    Uses the monotonic relationship: finer grind → less output, coarser → more.
    Estimates grind sensitivity (g output per grind step) from history, then
    computes how many steps to adjust based on the latest shot's deviation.
    """
    coffee = conn.execute(
        "SELECT default_grams_out FROM coffees WHERE id = ?", (coffee_id,)
    ).fetchone()
    target_out = coffee["default_grams_out"] if coffee else None
    if not target_out or target_out <= 0:
        return {"grind": None, "confidence": "low",
                "detail": "Set a target output weight (default grams out) on this coffee to use ratio optimization."}

    filt = _grind_filter_params(conn)
    rows = conn.execute(
        """SELECT s.grind_size, s.grams_out, s.grams_in, s.brew_temp_c,
                  s.brew_time_sec, s.created_at
           FROM samples s JOIN evaluations e ON e.sample_id = s.id
           WHERE s.coffee_id = ? AND s.grams_out IS NOT NULL AND s.grind_size IS NOT NULL
           ORDER BY s.created_at""",
        (coffee_id,),
    ).fetchall()

    if not rows:
        prior = _cross_coffee_prior(coffee_id, conn)
        if prior:
            return {"grind": prior["grind"], "confidence": "low",
                    "detail": f"No shots yet. Your {prior['match']} average grind {prior['grind']} — try starting there. Target output: {target_out:.0f}g."}
        return None

    rows = _apply_recipe_filter(rows, filt)

    grinds = [r["grind_size"] for r in rows]
    outputs = [r["grams_out"] for r in rows]
    n = len(rows)

    # Check if a proven grind exists: 2+ shots at the same grind (±0.5) that
    # average within ±1g of target. This filters out lucky one-off outliers.
    from collections import defaultdict
    grind_groups = defaultdict(list)
    for r in rows:
        # Round to nearest 0.5 to group similar grinds
        key = round(r["grind_size"] * 2) / 2
        grind_groups[key].append(r["grams_out"])
    for grind_key, outs in grind_groups.items():
        if len(outs) >= 2:
            avg_out = sum(outs) / len(outs)
            if abs(avg_out - target_out) <= 1:
                return {"grind": round(grind_key, 1), "confidence": "high",
                        "detail": f"Grind {grind_key} averages {avg_out:.0f}g across {len(outs)} shots (target {target_out:.0f}g). Proven setting."}

    # Linear regression on (grind, output) for sensitivity + prediction
    sensitivity = DEFAULT_GRIND_SENSITIVITY
    slope = None
    g_mean = sum(grinds) / n
    o_mean = sum(outputs) / n
    if n >= 2:
        num = sum((g - g_mean) * (o - o_mean) for g, o in zip(grinds, outputs))
        den = sum((g - g_mean) ** 2 for g in grinds)
        if abs(den) > 1e-9:
            slope = num / den
            if abs(slope) > 0.1:
                sensitivity = abs(slope)

    # Compute residual scatter to report reliability
    scatter_note = ""
    if slope is not None and n >= 3:
        intercept = o_mean - slope * g_mean
        residuals = [o - (slope * g + intercept) for g, o in zip(grinds, outputs)]
        rmse = (sum(r ** 2 for r in residuals) / n) ** 0.5
        if rmse > 3:
            scatter_note = f" Output varies ±{rmse:.0f}g."

    finer_is_lower = filt.get("finer_is_lower", True)
    sign = 1 if finer_is_lower else -1
    latest_out = rows[-1]["grams_out"]
    latest_grind = rows[-1]["grind_size"]
    dev = latest_out - target_out

    # Latest shot is on target — keep that grind (even with 1 shot)
    if abs(dev) <= 1:
        return {"grind": round(latest_grind, 1), "confidence": "medium" if n < 4 else "high",
                "detail": f"Last shot hit {latest_out:.0f}g (target {target_out:.0f}g). Keep grind at {latest_grind}."}

    if slope is not None and abs(slope) > 0.1 and n >= 2:
        intercept = o_mean - slope * g_mean
        predicted_grind = (target_out - intercept) / slope
        suggested = round(predicted_grind, 1)
        detail = f"Last shot: {latest_out:.0f}g (target {target_out:.0f}g, {dev:+.0f}g). Regression suggests grind {suggested} ({n} shots).{scatter_note}"
    else:
        latest_grind = rows[-1]["grind_size"]
        steps = dev / sensitivity
        suggested = round(latest_grind - sign * steps, 1)
        direction = "finer" if dev > 0 else "coarser"
        detail = f"Last shot: {latest_out:.0f}g (target {target_out:.0f}g, {dev:+.0f}g). Try {direction} by ~{abs(steps):.1f} steps."

    conf = "medium" if n < 4 else "high"
    return {"grind": suggested, "confidence": conf, "detail": detail}


# --- Step 1: Select or define coffee ---

SORT_OPTIONS = {"rating", "roasted", "opened"}


@app.route("/")
def index():
    show_archived = request.args.get("archived") == "1"
    sort_by = request.args.get("sort", "")
    sort_dir = request.args.get("dir", "")
    # Persist sort choice: save if provided, load if not
    with get_db() as conn:
        if sort_by and sort_by in SORT_OPTIONS:
            set_setting(conn, "coffee_sort", sort_by)
            if sort_dir in ("asc", "desc"):
                set_setting(conn, "coffee_sort_dir", sort_dir)
        else:
            sort_by = get_setting(conn, "coffee_sort", "roasted")
            sort_dir = ""
        if sort_by not in SORT_OPTIONS:
            sort_by = "roasted"
        if not sort_dir:
            sort_dir = get_setting(conn, "coffee_sort_dir", "")
        if sort_dir not in ("asc", "desc"):
            # Default direction per sort type
            sort_dir = "desc" if sort_by == "rating" else "asc"
        card_design = get_setting(conn, "card_design", "modern")
        if show_archived:
            coffees = conn.execute(
                "SELECT * FROM coffees WHERE archived = 1 ORDER BY updated_at DESC"
            ).fetchall()
        else:
            coffees = conn.execute(
                "SELECT * FROM coffees WHERE archived = 0 ORDER BY created_at DESC"
            ).fetchall()
        # Compute used grams per coffee
        usage = {}
        for row in conn.execute(
            "SELECT coffee_id, SUM(grams_in) as total_used FROM samples GROUP BY coffee_id"
        ).fetchall():
            usage[row["coffee_id"]] = row["total_used"]
    coffee_data = []
    # Separate connection needed: coffee_rating() runs per-coffee queries
    with get_db() as conn2:
        for c in coffees:
            cd = dict(c)
            cd["freshness"] = freshness_status(c)
            cd["tasting_chips"] = render_tasting_notes(c["tasting_notes"])
            cd["rating"] = coffee_rating(c["id"], conn2)
            cd["grams_used"] = usage.get(c["id"], 0)
            cd["days_open"] = days_since(c["opened_date"])
            cd["origin_map"] = ORIGIN_MAP_INDEX.get((c["origin_country"] or "").lower())
            if c["bag_weight_g"]:
                cd["grams_left"] = max(0, c["bag_weight_g"] - cd["grams_used"])
            else:
                cd["grams_left"] = None
            if c["bag_price"] and c["bag_weight_g"]:
                dose = c["default_grams_in"] or 18
                cd["cost_per_shot"] = (c["bag_price"] / c["bag_weight_g"]) * dose
            else:
                cd["cost_per_shot"] = None
            # Format altitude for display
            alt_min = c["altitude_min"]
            alt_max = c["altitude_max"]
            if alt_min and alt_max and alt_min != alt_max:
                cd["altitude_display"] = f"{alt_min}–{alt_max}m"
            elif alt_min:
                cd["altitude_display"] = f"{alt_min}m"
            elif alt_max:
                cd["altitude_display"] = f"{alt_max}m"
            else:
                cd["altitude_display"] = None
            coffee_data.append(cd)

    # Sort
    reverse = (sort_dir == "desc")
    if sort_by == "rating":
        coffee_data.sort(key=lambda c: c["rating"]["quality"] if c["rating"] else 0, reverse=reverse)
    elif sort_by == "roasted":
        coffee_data.sort(key=lambda c: c["freshness"]["days"] if c["freshness"] else 9999, reverse=reverse)
    elif sort_by == "opened":
        coffee_data.sort(key=lambda c: c["days_open"] if c["days_open"] is not None else 9999, reverse=reverse)

    return render_template("step1_coffee.html", coffees=coffee_data,
                           show_archived=show_archived, sort_by=sort_by, sort_dir=sort_dir,
                           card_design=card_design)


def parse_coffee_form(data):
    """Extract and validate all coffee fields from form submission data."""
    label = data.get("label", "").strip() or make_label(data)
    def_min = data.get("default_brew_min", "").strip()
    def_sec = data.get("default_brew_sec", "").strip()
    def_time = None
    if def_min or def_sec:
        def_time = safe_int(def_min, 0) * 60 + safe_int(def_sec, 0)
    bag_weight = data.get("bag_weight_g", "").strip()
    bag_price = data.get("bag_price", "").strip()
    best_after = data.get("best_after_days", "").strip()
    consume_within = data.get("consume_within_days", "").strip()

    return {
        "roaster": data.get("roaster", "").strip() or None,
        "origin_country": data.get("origin_country", "").strip() or None,
        "origin_city": data.get("origin_city", "").strip() or None,
        "origin_producer": data.get("origin_producer", "").strip() or None,
        "variety": data.get("variety", "").strip() or None,
        "process": data.get("process", "").strip() or None,
        "tasting_notes": data.get("tasting_notes", "").strip() or None,
        "label": label,
        "roast_date": data.get("roast_date", "").strip() or None,
        "best_after_days": safe_int(best_after) if best_after else None,
        "consume_within_days": safe_int(consume_within) if consume_within else None,
        "bag_weight_g": safe_float(bag_weight),
        "bag_price": safe_float(bag_price),
        "default_grams_in": safe_float(data.get("default_grams_in", "").strip()),
        "default_grams_out": safe_float(data.get("default_grams_out", "").strip()),
        "default_brew_time_sec": def_time,
        "bean_color": data.get("bean_color", "").strip() or None,
        "bean_size": data.get("bean_size", "").strip() or None,
        "altitude_min": safe_int(data.get("altitude_min", "").strip()),
        "altitude_max": safe_int(data.get("altitude_max", "").strip()),
        "opened_date": data.get("opened_date", "").strip() or None,
    }


@app.route("/coffee/add", methods=["POST"])
def add_coffee():
    fields = parse_coffee_form(request.form)
    # Guard against SQL injection from unexpected columns
    if not all(c in COFFEE_COLUMNS for c in fields.keys()):
        return redirect(url_for("index"))
    cols = list(fields.keys())
    placeholders = ", ".join("?" for _ in cols)
    with get_db() as conn:
        cur = conn.execute(
            f"INSERT INTO coffees ({', '.join(cols)}) VALUES ({placeholders})",
            [fields[c] for c in cols],
        )
        coffee_id = cur.lastrowid
    return redirect(url_for("new_sample", coffee_id=coffee_id))


@app.route("/coffee/<int:coffee_id>/edit")
def edit_coffee(coffee_id):
    with get_db() as conn:
        coffee = conn.execute("SELECT * FROM coffees WHERE id = ?", (coffee_id,)).fetchone()
    if not coffee:
        return redirect(url_for("index"))
    return render_template("edit_coffee.html", coffee=coffee)


@app.route("/coffee/<int:coffee_id>/edit", methods=["POST"])
def save_coffee(coffee_id):
    fields = parse_coffee_form(request.form)
    # Guard against SQL injection from unexpected columns
    if not all(c in COFFEE_COLUMNS for c in fields.keys()):
        return redirect(url_for("index"))
    set_clause = ", ".join(f"{c}=?" for c in fields.keys())
    with get_db() as conn:
        conn.execute(
            f"UPDATE coffees SET {set_clause}, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            list(fields.values()) + [coffee_id],
        )
    return redirect(url_for("index"))


@app.route("/coffee/<int:coffee_id>/archive", methods=["POST"])
def archive_coffee(coffee_id):
    with get_db() as conn:
        coffee = conn.execute("SELECT archived FROM coffees WHERE id = ?", (coffee_id,)).fetchone()
        if coffee:
            new_state = 0 if coffee["archived"] else 1
            conn.execute("UPDATE coffees SET archived = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                         (new_state, coffee_id))
    return redirect(url_for("index"))


@app.route("/coffee/<int:coffee_id>/delete", methods=["POST"])
def delete_coffee(coffee_id):
    with get_db() as conn:
        # Store for undo
        coffee = conn.execute("SELECT * FROM coffees WHERE id = ?", (coffee_id,)).fetchone()
        samples = conn.execute("SELECT * FROM samples WHERE coffee_id = ?", (coffee_id,)).fetchall()
        evals = []
        for s in samples:
            ev = conn.execute("SELECT * FROM evaluations WHERE sample_id = ?", (s["id"],)).fetchone()
            if ev:
                evals.append(dict(ev))
        if coffee:
            session["undo"] = {
                "type": "coffee",
                "coffee": {k: coffee[k] for k in coffee.keys()},
                "samples": [{k: s[k] for k in s.keys()} for s in samples],
                "evaluations": evals,
            }
        conn.execute("DELETE FROM evaluations WHERE sample_id IN (SELECT id FROM samples WHERE coffee_id = ?)", (coffee_id,))
        conn.execute("DELETE FROM samples WHERE coffee_id = ?", (coffee_id,))
        conn.execute("DELETE FROM coffees WHERE id = ?", (coffee_id,))
    return redirect(url_for("index"))


# --- Step 2: Log a sample ---

@app.route("/sample/<int:coffee_id>")
def new_sample(coffee_id):
    with get_db() as conn:
        coffee = conn.execute("SELECT * FROM coffees WHERE id = ?", (coffee_id,)).fetchone()
        samples = conn.execute(
            """SELECT s.*, e.aroma, e.acidity, e.sweetness, e.body, e.balance, e.overall
               FROM samples s LEFT JOIN evaluations e ON e.sample_id = s.id
               WHERE s.coffee_id = ? ORDER BY s.created_at DESC LIMIT 20""",
            (coffee_id,),
        ).fetchall()
    if not coffee:
        return redirect(url_for("index"))
    # If bag not yet opened, show "open bag?" dialog
    if not coffee["opened_date"] and not request.args.get("skip_open_check"):
        return render_template("open_bag.html", coffee=coffee)
    freshness = freshness_status(coffee)
    # Grind aroma prefill: sticky from last evaluation of this coffee.
    # See evaluate_sample() for the full prefill priority chain.
    grind_hint = None
    with get_db() as conn:
        grind_hint = suggest_grind(coffee_id, conn)
        last_eval = conn.execute(
            """SELECT e.grind_aroma, e.aroma_descriptors
               FROM evaluations e JOIN samples s ON e.sample_id = s.id
               WHERE s.coffee_id = ? AND e.grind_aroma IS NOT NULL
               ORDER BY e.created_at DESC LIMIT 1""",
            (coffee_id,),
        ).fetchone()
    days_open = days_since(coffee["opened_date"])
    prefill_grind_aroma = last_eval["grind_aroma"] if last_eval else None
    prefill_grind_smell = (last_eval["aroma_descriptors"] or "").split(",") if last_eval and last_eval["aroma_descriptors"] else []
    return render_template("step2_sample.html", coffee=coffee, samples=samples,
                           freshness=freshness, grind_hint=grind_hint, days_open=days_open,
                           prefill_grind_aroma=prefill_grind_aroma,
                           prefill_grind_smell=prefill_grind_smell)


@app.route("/coffee/<int:coffee_id>/open", methods=["POST"])
def open_bag(coffee_id):
    """Set today as the opened_date for a coffee and redirect to sample page."""
    with get_db() as conn:
        conn.execute("UPDATE coffees SET opened_date = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                     (date.today().isoformat(), coffee_id))
    return redirect(url_for("new_sample", coffee_id=coffee_id))


@app.route("/sample/<int:coffee_id>/add", methods=["POST"])
def add_sample(coffee_id):
    data = request.form
    minutes = safe_int(data.get("brew_min"), 0)
    seconds = safe_int(data.get("brew_sec"), 0)
    brew_time_sec = minutes * 60 + seconds

    brew_temp = data.get("brew_temp_c", "").strip()
    # Grind aroma + smell captured on sample page, carried to eval via query params.
    # Not stored on samples — only persisted when the user saves the evaluation.
    grind_smell = ",".join(data.getlist("grind_smell")) or None
    grind_aroma = data.get("grind_aroma") or None

    with get_db() as conn:

        coffee = conn.execute("SELECT roast_date, opened_date FROM coffees WHERE id = ?", (coffee_id,)).fetchone()
        days_since_roast = days_since(coffee["roast_date"]) if coffee else None
        days_since_opened = days_since(coffee["opened_date"]) if coffee else None

        cur = conn.execute(
            """INSERT INTO samples (coffee_id, grind_size, grams_in, grams_out, brew_time_sec, brew_temp_c, days_since_roast, days_since_opened, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                coffee_id,
                safe_float(data["grind_size"], 0),
                safe_float(data["grams_in"], 0),
                safe_float(data["grams_out"], 0),
                brew_time_sec,
                safe_float(brew_temp, 91),
                days_since_roast,
                days_since_opened,
                data.get("notes", ""),
            ),
        )
        sample_id = cur.lastrowid
    return redirect(url_for("evaluate_sample", sample_id=sample_id,
                            grind_smell=grind_smell, grind_aroma=grind_aroma))


@app.route("/sample/<int:sample_id>/delete", methods=["POST"])
def delete_sample(sample_id):
    with get_db() as conn:
        sample = conn.execute("SELECT * FROM samples WHERE id = ?", (sample_id,)).fetchone()
        ev = conn.execute("SELECT * FROM evaluations WHERE sample_id = ?", (sample_id,)).fetchone()
        if sample:
            session["undo"] = {
                "type": "sample",
                "sample": {k: sample[k] for k in sample.keys()},
                "evaluation": dict(ev) if ev else None,
            }
        coffee_id = sample["coffee_id"] if sample else None
        conn.execute("DELETE FROM evaluations WHERE sample_id = ?", (sample_id,))
        conn.execute("DELETE FROM samples WHERE id = ?", (sample_id,))
    if coffee_id:
        return redirect(url_for("new_sample", coffee_id=coffee_id))
    return redirect(url_for("index"))


@app.route("/sample/<int:sample_id>/edit")
def edit_sample(sample_id):
    """Show edit form for a sample's brew parameters."""
    with get_db() as conn:
        sample = conn.execute("SELECT * FROM samples WHERE id = ?", (sample_id,)).fetchone()
        if not sample:
            return redirect(url_for("index"))
        coffee = conn.execute("SELECT * FROM coffees WHERE id = ?", (sample["coffee_id"],)).fetchone()
        all_coffees = conn.execute("SELECT id, label FROM coffees WHERE archived = 0 ORDER BY label").fetchall()
    from_eval = request.args.get("from") == "eval"
    return render_template("edit_sample.html", sample=sample, coffee=coffee,
                           all_coffees=all_coffees, from_eval=from_eval)


@app.route("/sample/<int:sample_id>/edit", methods=["POST"])
def save_sample(sample_id):
    """Save edited sample brew parameters and/or move to different coffee."""
    data = request.form
    new_coffee_id = safe_int(data.get("coffee_id"))
    with get_db() as conn:
        sample = conn.execute("SELECT * FROM samples WHERE id = ?", (sample_id,)).fetchone()
        if not sample:
            return redirect(url_for("index"))
        if new_coffee_id and not conn.execute("SELECT id FROM coffees WHERE id = ?", (new_coffee_id,)).fetchone():
            return redirect(url_for("new_sample", coffee_id=sample["coffee_id"]))
        conn.execute(
            """UPDATE samples SET coffee_id=?, grind_size=?, grams_in=?, grams_out=?,
               brew_time_sec=?, brew_temp_c=? WHERE id=?""",
            (
                new_coffee_id or sample["coffee_id"],
                safe_float(data.get("grind_size"), sample["grind_size"]),
                safe_float(data.get("grams_in"), sample["grams_in"]),
                safe_float(data.get("grams_out"), sample["grams_out"]),
                safe_int(data.get("brew_sec"), sample["brew_time_sec"]),
                safe_float(data.get("brew_temp_c"), sample["brew_temp_c"]),
                sample_id,
            ),
        )
    if data.get("from_eval"):
        return redirect(url_for("evaluate_sample", sample_id=sample_id))
    target = new_coffee_id or sample["coffee_id"]
    return redirect(url_for("new_sample", coffee_id=target))


@app.route("/undo", methods=["POST"])
def undo_delete():
    undo = session.pop("undo", None)
    if not undo:
        return redirect(url_for("index"))

    with get_db() as conn:
        if undo["type"] == "coffee":
            c = undo["coffee"]
            cols = [k for k in c if k != "id" and k in COFFEE_COLUMNS]
            placeholders = ",".join("?" for _ in cols)
            conn.execute(
                f"INSERT INTO coffees ({','.join(cols)}) VALUES ({placeholders})",
                [c[k] for k in cols],
            )
            new_cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            for s in undo.get("samples", []):
                old_sid = s["id"]
                s_cols = [k for k in s if k not in ("id", "ratio") and k in SAMPLE_COLUMNS]
                s_vals = [new_cid if k == "coffee_id" else s[k] for k in s_cols]
                conn.execute(
                    f"INSERT INTO samples ({','.join(s_cols)}) VALUES ({','.join('?' for _ in s_cols)})",
                    s_vals,
                )
                new_sid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                for ev in undo.get("evaluations", []):
                    if ev.get("sample_id") == old_sid:
                        ev_cols = [k for k in ev if k not in ("id", "sample_id") and k in EVALUATION_COLUMNS]
                        conn.execute(
                            f"INSERT INTO evaluations (sample_id,{','.join(ev_cols)}) VALUES (?,{','.join('?' for _ in ev_cols)})",
                            [new_sid] + [ev[k] for k in ev_cols],
                        )
            return redirect(url_for("new_sample", coffee_id=new_cid))

        elif undo["type"] == "sample":
            s = undo["sample"]
            s_cols = [k for k in s if k not in ("id", "ratio") and k in SAMPLE_COLUMNS]
            conn.execute(
                f"INSERT INTO samples ({','.join(s_cols)}) VALUES ({','.join('?' for _ in s_cols)})",
                [s[k] for k in s_cols],
            )
            new_sid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            ev = undo.get("evaluation")
            if ev:
                ev_cols = [k for k in ev if k not in ("id", "sample_id") and k in EVALUATION_COLUMNS]
                conn.execute(
                    f"INSERT INTO evaluations (sample_id,{','.join(ev_cols)}) VALUES (?,{','.join('?' for _ in ev_cols)})",
                    [new_sid] + [ev[k] for k in ev_cols],
                )
            return redirect(url_for("new_sample", coffee_id=s["coffee_id"]))

    return redirect(url_for("index"))


# --- Cross-Coffee Insights ---

@app.route("/insights")
def insights():
    """Cross-coffee insights page with groupings by process, variety, origin, roast level."""
    # Filter options from query params
    rep_only = request.args.get("rep", "0") == "1"
    min_score = safe_float(request.args.get("min"), 0)  # 0 = no filter

    rep_filter = "AND e.representative = 1" if rep_only else ""
    score_filter = "AND e.overall >= ?" if min_score > 0 else ""
    query_params = [min_score] if min_score > 0 else []

    with get_db() as conn:
        rows = conn.execute(f"""
            SELECT c.id, c.label, c.process, c.variety, c.origin_country, c.bean_color,
                   c.bag_price, c.bag_weight_g, c.archived,
                   AVG(e.aroma) as avg_aroma, AVG(e.acidity) as avg_acidity,
                   AVG(e.sweetness) as avg_sweetness, AVG(e.body) as avg_body,
                   AVG(e.balance) as avg_balance, AVG(e.overall) as avg_overall,
                   AVG(s.grind_size) as avg_grind, AVG(s.brew_time_sec) as avg_time,
                   AVG(s.brew_temp_c) as avg_temp,
                   MIN(s.grind_size) as min_grind, MAX(s.grind_size) as max_grind,
                   AVG(e.overall * e.overall) - AVG(e.overall) * AVG(e.overall) as score_variance,
                   COUNT(DISTINCT s.id) as shot_count,
                   AVG(s.days_since_roast) as avg_days_roast,
                   AVG(s.grams_in) as avg_dose
            FROM coffees c
            JOIN samples s ON s.coffee_id = c.id
            JOIN evaluations e ON e.sample_id = s.id
            WHERE e.overall IS NOT NULL {rep_filter} {score_filter}
            GROUP BY c.id
        """, query_params).fetchall()

    if not rows:
        return render_template("insights.html", process_chart="[]", origin_chart="[]",
                               roast_chart="[]", process_radar="[]",
                               findings=[], totals={"coffees": 0, "shots": 0},
                               rep_only=rep_only, min_score=min_score)

    coffees = [dict(r) for r in rows]

    # Compute preference-weighted quality per coffee (same formula as coffee_rating)
    with get_db() as conn_prefs:
        prefs = _taste_preferences(conn_prefs)
    for c in coffees:
        num = (c["avg_balance"] or 3) + 2 * (c["avg_overall"] or 3)
        den = 3.0
        for d in TASTE_PREF_DIMS:
            w = (prefs[d] - 3) / 2.0
            if abs(w) > 0.01:
                num += w * (c[f"avg_{d}"] or 3)
                den += abs(w)
        c["quality"] = round(max(1.0, min(5.0, num / den)), 1) if den > 0 else c["avg_overall"]

    # --- Helpers ---
    def group_by(key):
        groups = {}
        for c in coffees:
            val = c.get(key) or "Unknown"
            groups.setdefault(val, []).append(c)
        return groups

    def gavg(group, metric):
        """Shot-weighted average of a metric across coffees in a group."""
        pairs = [(c[metric], c["shot_count"]) for c in group if c[metric] is not None]
        if not pairs:
            return None
        total_w = sum(w for _, w in pairs)
        if total_w == 0:
            return None
        return round(sum(v * w for v, w in pairs) / total_w, 1)

    def build_chart(grouping):
        """Build sorted chart data for a grouping dict."""
        chart = []
        for name, group in grouping.items():
            chart.append({
                "name": name, "count": len(group),
                "overall": gavg(group, "avg_overall"),
                "sweetness": gavg(group, "avg_sweetness"),
                "acidity": gavg(group, "avg_acidity"),
                "body": gavg(group, "avg_body"),
                "aroma": gavg(group, "avg_aroma"),
                "balance": gavg(group, "avg_balance"),
                "grind": gavg(group, "avg_grind"),
            })
        return sorted(chart, key=lambda x: x["overall"] or 0, reverse=True)

    # --- Groupings ---
    by_process = group_by("process")
    by_origin = group_by("origin_country")
    by_roast = group_by("bean_color")

    process_chart = build_chart(by_process)
    origin_chart = build_chart(by_origin)
    roast_chart = build_chart(by_roast)

    # --- Organized findings ---
    findings = []
    total_shots = sum(c["shot_count"] for c in coffees)
    total_coffees = len(coffees)

    # Top rated (by preference-weighted quality)
    best = max(coffees, key=lambda c: c["quality"] or 0)
    findings.append({"cat": "Top", "text": f"Top rated: {best['label']} ({best['quality']}/5, {best['shot_count']} shot{'s' if best['shot_count'] != 1 else ''})"})

    # Process insights: avg rating + grind range
    for proc, group in sorted(by_process.items(), key=lambda x: gavg(x[1], "quality") or 0, reverse=True):
        avg_ov = gavg(group, "quality")
        with_grind = [c for c in group if c["avg_grind"]]
        if with_grind:
            grinds = [c["avg_grind"] for c in with_grind]
            grind_part = f", grind {min(grinds):.1f}–{max(grinds):.1f}" if len(grinds) > 1 else f", grind {grinds[0]:.1f}"
        else:
            grind_part = ""
        shots = sum(c["shot_count"] for c in group)
        findings.append({"cat": "Process", "text":
            f"{proc}: avg {avg_ov}/5 ({len(group)} coffee{'s' if len(group) != 1 else ''}, {shots} shot{'s' if shots != 1 else ''}){grind_part}"})

    # Flavor standouts
    sweetest = max(coffees, key=lambda c: c["avg_sweetness"] or 0)
    findings.append({"cat": "Flavor", "text": f"Sweetest: {sweetest['label']} ({sweetest['avg_sweetness']:.1f}/5, {sweetest['shot_count']} shot{'s' if sweetest['shot_count'] != 1 else ''})"})
    brightest = max(coffees, key=lambda c: c["avg_acidity"] or 0)
    findings.append({"cat": "Flavor", "text": f"Brightest: {brightest['label']} ({brightest['avg_acidity']:.1f}/5 acidity, {brightest['shot_count']} shot{'s' if brightest['shot_count'] != 1 else ''})"})
    fullest = max(coffees, key=lambda c: c["avg_body"] or 0)
    findings.append({"cat": "Flavor", "text": f"Fullest body: {fullest['label']} ({fullest['avg_body']:.1f}/5, {fullest['shot_count']} shot{'s' if fullest['shot_count'] != 1 else ''})"})

    # Cross-cutting insights (process + origin combinations)
    for c in coffees:
        if (c["quality"] or 0) >= 4.0:
            proc = c["process"] or "Unknown"
            origin = c["origin_country"] or "Unknown"
            variety = c["variety"] or "Unknown"
            findings.append({"cat": "Cross", "text":
                f"{proc} {origin} {variety}: {c['quality']}/5 quality ({c['shot_count']} shot{'s' if c['shot_count'] != 1 else ''})"})

    # Roast insights
    if len(by_roast) > 1:
        for roast, group in by_roast.items():
            if roast != "Unknown":
                shots = sum(c["shot_count"] for c in group)
                findings.append({"cat": "Roast", "text":
                    f"{roast} roasts: acidity {gavg(group, 'avg_acidity') or '?'}, body {gavg(group, 'avg_body') or '?'}, grind {gavg(group, 'avg_grind') or 0:.1f} ({shots} shot{'s' if shots != 1 else ''})"})

    # Value — price per shot normalized by quality
    priced = [c for c in coffees if c["bag_price"] and c["bag_weight_g"] and (c["quality"] or 0) > 0]
    for c in priced:
        dose = c["avg_dose"] or 18
        c["cost_per_shot"] = (c["bag_price"] / c["bag_weight_g"]) * dose
        c["value_score"] = c["cost_per_shot"] / c["quality"]
    if len(priced) >= 2:
        best_val = min(priced, key=lambda c: c["value_score"])
        findings.append({"cat": "Value", "text":
            f"Best value: {best_val['label']} ({best_val['cost_per_shot']:.2f}€/shot, {best_val['quality']}/5, {best_val['shot_count']} shot{'s' if best_val['shot_count'] != 1 else ''})"})

    # Forgiveness — score consistency across grind variation
    for c in coffees:
        variance = c["score_variance"] or 0
        stddev = variance ** 0.5 if variance > 0 else 0
        # Need 4+ shots with known grind range of at least 2 steps
        has_grind = c["min_grind"] is not None and c["max_grind"] is not None
        grind_range = (c["max_grind"] - c["min_grind"]) if has_grind else 0
        if c["shot_count"] >= 4 and has_grind and grind_range >= 2:
            if stddev <= 0.5:
                c["forgiveness"] = "Very Forgiving"
            elif stddev <= 1.0:
                c["forgiveness"] = "Forgiving"
            elif stddev <= 1.5:
                c["forgiveness"] = "Moderate"
            else:
                c["forgiveness"] = "Demanding"
        else:
            c["forgiveness"] = None

    forgiving = [c for c in coffees if c.get("forgiveness") in ("Very Forgiving", "Forgiving")]
    demanding = [c for c in coffees if c.get("forgiveness") == "Demanding"]
    if forgiving:
        best_f = max(forgiving, key=lambda c: c["quality"] or 0)
        findings.append({"cat": "Dial-in", "text":
            f"Easy to dial in: {best_f['label']} — tastes good even when grind is off (scored {best_f['quality']}/5 across grind {best_f['min_grind']:.1f}–{best_f['max_grind']:.1f})"})
    if demanding:
        worst_d = max(demanding, key=lambda c: c["quality"] or 0)
        findings.append({"cat": "Dial-in", "text":
            f"Hard to dial in: {worst_d['label']} — scores swing a lot with small grind changes, nail it at ~{worst_d['avg_grind']:.1f}"})

    totals = {"coffees": total_coffees, "shots": total_shots}

    # Radar overlay: all processes
    dims = ["aroma", "acidity", "sweetness", "body", "balance"]
    process_radar = []
    for proc, group in sorted(by_process.items(), key=lambda x: gavg(x[1], "avg_overall") or 0, reverse=True):
        process_radar.append({
            "name": proc,
            "data": [gavg(group, f"avg_{d}") or 0 for d in dims],
        })

    return render_template("insights.html",
                           process_chart=json.dumps(process_chart),
                           origin_chart=json.dumps(origin_chart),
                           roast_chart=json.dumps(roast_chart),
                           process_radar=json.dumps(process_radar),
                           findings=findings, totals=totals,
                           rep_only=rep_only,
                           min_score=min_score)


# --- Coffee Stats & Charts ---

@app.route("/stats/<int:coffee_id>")
def coffee_stats(coffee_id):
    with get_db() as conn:
        coffee = conn.execute("SELECT * FROM coffees WHERE id = ?", (coffee_id,)).fetchone()
        if not coffee:
            return redirect(url_for("index"))

        samples = conn.execute(
            """SELECT s.*, e.aroma, e.acidity, e.sweetness, e.body, e.balance, e.overall, e.representative
               FROM samples s LEFT JOIN evaluations e ON e.sample_id = s.id
               WHERE s.coffee_id = ? ORDER BY s.created_at ASC""",
            (coffee_id,),
        ).fetchall()

        # All coffees for cross-coffee comparison (include archived)
        all_coffees = conn.execute("SELECT id, label, process, archived FROM coffees").fetchall()
        cross_data = []
        for ac in all_coffees:
            avgs = conn.execute(
                """SELECT AVG(e.aroma) as aroma, AVG(e.acidity) as acidity,
                          AVG(e.sweetness) as sweetness, AVG(e.body) as body,
                          AVG(e.balance) as balance, AVG(e.overall) as overall,
                          COUNT(*) as n
                   FROM evaluations e JOIN samples s ON e.sample_id = s.id
                   WHERE s.coffee_id = ? AND e.overall IS NOT NULL""",
                (ac["id"],),
            ).fetchone()
            if avgs and avgs["n"] > 0:
                cross_data.append({
                    "id": ac["id"], "label": ac["label"],
                    "process": ac["process"] or "?",
                    "archived": ac["archived"],
                    "aroma": round(avgs["aroma"], 1),
                    "acidity": round(avgs["acidity"], 1),
                    "sweetness": round(avgs["sweetness"], 1),
                    "body": round(avgs["body"], 1),
                    "balance": round(avgs["balance"], 1),
                    "overall": round(avgs["overall"], 1),
                    "shots": avgs["n"],
                })

        rating = coffee_rating(coffee_id, conn) if samples else None

    freshness = freshness_status(coffee)

    # Build chart data
    evaluated = [dict(s) for s in samples if s["overall"] is not None]
    representative = [s for s in evaluated if s["representative"]]

    # Timeline data (all evaluated shots)
    timeline = [{"date": s["created_at"][:10], "score": s["overall"], "grind": s["grind_size"]} for s in evaluated]

    # Grind vs score
    grind_scores = [{"grind": s["grind_size"], "score": s["overall"]} for s in evaluated]

    # Radar chart (average of representative, or all if no rep)
    radar_source = representative if representative else evaluated
    dims = ["aroma", "acidity", "sweetness", "body", "balance"]
    if radar_source:
        radar = {d: round(sum(s[d] or 0 for s in radar_source) / len(radar_source), 1) for d in dims}
    else:
        radar = None

    # Key stats
    stats = {
        "total_shots": len(samples),
        "evaluated": len(evaluated),
        "representative": len(representative),
    }
    if evaluated:
        stats["avg_score"] = round(sum(s["overall"] for s in evaluated) / len(evaluated), 1)
        best = max(evaluated, key=lambda s: s["overall"])
        stats["best_grind"] = best["grind_size"]
        stats["best_score"] = best["overall"]
        stats["avg_ratio"] = round(sum(s["ratio"] or 0 for s in evaluated) / len(evaluated), 1)

    days_open = days_since(coffee["opened_date"])

    return render_template("stats.html", coffee=coffee, freshness=freshness, rating=rating,
                           stats=stats, timeline=json.dumps(timeline),
                           grind_scores=json.dumps(grind_scores),
                           radar=json.dumps(radar), cross_data=json.dumps(cross_data),
                           days_open=days_open)


# --- Step 3: Evaluate a sample ---

@app.route("/evaluate/<int:sample_id>")
def evaluate_sample(sample_id):
    with get_db() as conn:
        sample = conn.execute("SELECT * FROM samples WHERE id = ?", (sample_id,)).fetchone()
        if not sample:
            return redirect(url_for("index"))
        coffee = conn.execute("SELECT * FROM coffees WHERE id = ?", (sample["coffee_id"],)).fetchone()
        existing = conn.execute("SELECT * FROM evaluations WHERE sample_id = ?", (sample_id,)).fetchone()
        # Grind aroma prefill priority chain:
        # 1. Existing evaluation (re-editing) — handled in template
        # 2. Query params from sample page (user's fresh selections)
        # 3. Sticky: last evaluation of this coffee (same grind aroma carries forward)
        last_eval = conn.execute(
            """SELECT e.grind_aroma, e.aroma_descriptors
               FROM evaluations e JOIN samples s ON e.sample_id = s.id
               WHERE s.coffee_id = ? AND e.grind_aroma IS NOT NULL
               ORDER BY e.created_at DESC LIMIT 1""",
            (sample["coffee_id"],),
        ).fetchone()
    freshness = freshness_status(coffee)
    # Query params (from sample page) override sticky prefill (from last eval)
    prefill_grind_aroma = safe_int(request.args.get("grind_aroma")) or (last_eval["grind_aroma"] if last_eval else None)
    prefill_grind_smell = request.args.get("grind_smell") or (last_eval["aroma_descriptors"] if last_eval and last_eval["aroma_descriptors"] else None)
    return render_template(
        "step3_evaluate.html",
        coffee=coffee, sample=sample, evaluation=existing,
        dimensions=EVAL_DIMENSIONS, tips=None, freshness=freshness,
        prefill_grind_aroma=prefill_grind_aroma,
        prefill_grind_smell=prefill_grind_smell,
    )


@app.route("/evaluate/<int:sample_id>/save", methods=["POST"])
def save_evaluation(sample_id):
    data = request.form
    scores = {}
    for dim in EVAL_DIMENSIONS:
        val = data.get(dim["key"])
        scores[dim["key"]] = safe_int(val)
    representative = 1 if data.get("representative") else 0
    grind_aroma = safe_int(data.get("grind_aroma"))
    preheat_pf = 1 if data.get("preheat_portafilter") else 0
    preheat_cup = 1 if data.get("preheat_cup") else 0
    preheat_machine = 1 if data.get("preheat_machine") else 0
    eval_notes = data.get("eval_notes", "").strip() or None
    with_milk = 1 if data.get("with_milk") else 0
    aroma_desc = ",".join(data.getlist("aroma_descriptors")) or None
    brew_smell_desc = ",".join(data.getlist("brew_smell_descriptors")) or None
    taste_desc = ",".join(data.getlist("taste_descriptors")) or None

    with get_db() as conn:
        sample = conn.execute("SELECT * FROM samples WHERE id = ?", (sample_id,)).fetchone()
        if not sample:
            return redirect(url_for("index"))
        coffee = conn.execute("SELECT * FROM coffees WHERE id = ?", (sample["coffee_id"],)).fetchone()

        conn.execute("""
    INSERT INTO evaluations (sample_id, aroma, acidity, sweetness, body, balance, overall,
       grind_aroma, aroma_descriptors, brew_smell_descriptors, taste_descriptors,
       preheat_portafilter, preheat_cup, preheat_machine,
       eval_notes, with_milk, representative)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(sample_id) DO UPDATE SET
       aroma=excluded.aroma, acidity=excluded.acidity, sweetness=excluded.sweetness,
       body=excluded.body, balance=excluded.balance, overall=excluded.overall,
       grind_aroma=excluded.grind_aroma, aroma_descriptors=excluded.aroma_descriptors,
       brew_smell_descriptors=excluded.brew_smell_descriptors,
       taste_descriptors=excluded.taste_descriptors,
       preheat_portafilter=excluded.preheat_portafilter,
       preheat_cup=excluded.preheat_cup, preheat_machine=excluded.preheat_machine,
       eval_notes=excluded.eval_notes, with_milk=excluded.with_milk,
       representative=excluded.representative
""", (sample_id, scores["aroma"], scores["acidity"], scores["sweetness"],
      scores["body"], scores["balance"], scores["overall"],
      grind_aroma, aroma_desc, brew_smell_desc, taste_desc, preheat_pf, preheat_cup, preheat_machine,
      eval_notes, with_milk, representative))

        evaluation = conn.execute("SELECT * FROM evaluations WHERE sample_id = ?", (sample_id,)).fetchone()
        freshness = freshness_status(coffee)

    # Compute ratio-based target output from actual input
    target_out = None
    if coffee and coffee["default_grams_in"] and coffee["default_grams_out"] and sample:
        ratio = coffee["default_grams_out"] / coffee["default_grams_in"]
        target_out = sample["grams_in"] * ratio if sample["grams_in"] else None
    actual_out = sample["grams_out"] if sample else None
    brew_time = sample["brew_time_sec"] if sample else None
    tips = diagnose(scores, taste_desc, actual_out, target_out, brew_time)
    return render_template(
        "step3_evaluate.html",
        coffee=coffee, sample=sample, evaluation=evaluation,
        dimensions=EVAL_DIMENSIONS, tips=tips, freshness=freshness,
        prefill_grind_aroma=None, prefill_grind_smell=None,
    )


# --- Settings: Custom tasting notes ---

@app.route("/settings/tasting-notes")
def settings_tasting_notes():
    with get_db() as conn:
        notes = conn.execute("SELECT * FROM custom_tasting_notes ORDER BY name").fetchall()
        overrides = {r["name"].lower(): r for r in notes}
    # Build full list: built-ins (with overrides) + pure custom
    builtin_names = set()
    builtin_list = []
    for name, emoji in sorted(TASTING_EMOJIS.items()):
        builtin_names.add(name)
        override = overrides.get(name)
        builtin_list.append({
            "name": name,
            "emoji": override["emoji"] if override else emoji,
            "default_emoji": emoji,
            "overridden": override is not None,
            "id": override["id"] if override else None,
        })
    custom_only = [dict(n) for n in notes if n["name"].lower() not in builtin_names]
    return render_template("settings_notes.html", builtins=builtin_list, custom=custom_only)


@app.route("/settings/tasting-notes/add", methods=["POST"])
def add_tasting_note():
    name = request.form.get("name", "").strip()
    emoji = request.form.get("emoji", "").strip()
    if name:
        with get_db() as conn:
            # Case-insensitive duplicate check (DB + built-in)
            existing = conn.execute(
                "SELECT id FROM custom_tasting_notes WHERE LOWER(name) = LOWER(?)", (name,)
            ).fetchone()
            if existing:
                return redirect(url_for("settings_tasting_notes", error="duplicate"))
            try:
                conn.execute("INSERT INTO custom_tasting_notes (name, emoji) VALUES (?, ?)", (name, emoji))
            except sqlite3.IntegrityError:
                return redirect(url_for("settings_tasting_notes", error="duplicate"))
    return redirect(url_for("settings_tasting_notes"))


@app.route("/settings/tasting-notes/<int:note_id>/edit", methods=["POST"])
def edit_tasting_note(note_id):
    name = request.form.get("name", "").strip()
    emoji = request.form.get("emoji", "").strip()
    if name:
        with get_db() as conn:
            conn.execute("UPDATE custom_tasting_notes SET name=?, emoji=? WHERE id=?",
                         (name, emoji, note_id))
    return redirect(url_for("settings_tasting_notes"))


@app.route("/settings/tasting-notes/override", methods=["POST"])
def override_builtin_note():
    name = request.form.get("name", "").strip()
    emoji = request.form.get("emoji", "").strip()
    if name:
        with get_db() as conn:
            existing = conn.execute(
                "SELECT id FROM custom_tasting_notes WHERE LOWER(name) = LOWER(?)", (name,)
            ).fetchone()
            if existing:
                conn.execute("UPDATE custom_tasting_notes SET emoji=? WHERE id=?", (emoji, existing["id"]))
            else:
                conn.execute("INSERT INTO custom_tasting_notes (name, emoji) VALUES (?, ?)", (name, emoji))
    return redirect(url_for("settings_tasting_notes"))


@app.route("/settings/tasting-notes/reset", methods=["POST"])
def reset_builtin_note():
    name = request.form.get("name", "").strip()
    if name:
        with get_db() as conn:
            conn.execute("DELETE FROM custom_tasting_notes WHERE LOWER(name) = LOWER(?)", (name,))
    return redirect(url_for("settings_tasting_notes"))


@app.route("/settings/tasting-notes/<int:note_id>/delete", methods=["POST"])
def delete_tasting_note(note_id):
    with get_db() as conn:
        conn.execute("DELETE FROM custom_tasting_notes WHERE id = ?", (note_id,))
    return redirect(url_for("settings_tasting_notes"))


@app.route("/api/custom-tasting-notes")
def api_custom_tasting_notes():
    with get_db() as conn:
        notes = conn.execute("SELECT name, emoji FROM custom_tasting_notes ORDER BY name").fetchall()
    return jsonify([dict(n) for n in notes])


@app.route("/settings/design")
def settings_design():
    with get_db() as conn:
        card_design = get_setting(conn, "card_design", "modern")
    return render_template("settings_design.html", card_design=card_design)


@app.route("/settings/design/save", methods=["POST"])
def save_design_settings():
    data = request.get_json(silent=True) or {}
    design = data.get("card_design", "modern")
    if design not in ("modern", "showcase", "legacy"):
        design = "modern"
    with get_db() as conn:
        set_setting(conn, "card_design", design)
    return jsonify({"ok": True})


@app.route("/settings/taste")
def settings_taste():
    with get_db() as conn:
        prefs = _taste_preferences(conn)
    dims = [
        {"key": "sweetness", "label": "Sweetness", "low": "Dislike", "high": "Love",
         "hint": "How much do you enjoy sweet, honey-like espresso?"},
        {"key": "acidity", "label": "Acidity", "low": "Dislike", "high": "Love",
         "hint": "Bright, fruity, citrusy notes. Some love it, some prefer mellow."},
        {"key": "body", "label": "Body", "low": "Dislike", "high": "Love",
         "hint": "Thick, creamy, syrupy mouthfeel vs thin, tea-like."},
        {"key": "aroma", "label": "Aroma", "low": "Don't care", "high": "Important",
         "hint": "How much does the smell of the coffee matter to your enjoyment?"},
    ]
    return render_template("settings_taste.html", prefs=prefs, dims=dims)


@app.route("/settings/taste/save", methods=["POST"])
def save_taste_settings():
    data = request.get_json(silent=True) or {}
    prefs = {}
    for d in TASTE_PREF_DIMS:
        val = safe_int(data.get(d), TASTE_PREF_DEFAULTS[d])
        prefs[d] = max(1, min(5, val))
    with get_db() as conn:
        set_setting(conn, "taste_preferences", json.dumps(prefs))
    return jsonify({"ok": True})


@app.route("/settings/grind")
def settings_grind():
    with get_db() as conn:
        algo = get_setting(conn, "grind_algorithm", "weighted_centroid")
        centroid_json = get_setting(conn, "grind_centroid_params", None)
        bayesian_json = get_setting(conn, "grind_bayesian_params", None)
        filter_json = get_setting(conn, "grind_filter_params", None)
    centroid_params = json.loads(centroid_json) if centroid_json else {}
    bayesian_params = json.loads(bayesian_json) if bayesian_json else {}
    filter_params = json.loads(filter_json) if filter_json else {}
    return render_template("settings_grind.html",
                           algo=algo,
                           centroid_params=centroid_params,
                           centroid_defaults=CENTROID_DEFAULTS,
                           bayesian_params=bayesian_params,
                           bayesian_defaults=BAYESIAN_DEFAULTS,
                           filter_params=filter_params,
                           filter_defaults=GRIND_FILTER_DEFAULTS,
                           score_sources=SCORE_SOURCES)


@app.route("/settings/grind/save", methods=["POST"])
def save_grind_settings():
    algo = request.form.get("algorithm", "weighted_centroid")
    if algo not in ("quadratic", "weighted_centroid", "bayesian_quadratic"):
        algo = "weighted_centroid"

    centroid_params = {
        "decay_rate": max(0, safe_float(request.form.get("centroid_decay_rate"), CENTROID_DEFAULTS["decay_rate"])),
        "top_n": max(1, safe_int(request.form.get("centroid_top_n"), CENTROID_DEFAULTS["top_n"])),
        "score_weight_power": max(0.5, safe_float(request.form.get("centroid_score_power"), CENTROID_DEFAULTS["score_weight_power"])),
    }
    bayesian_params = {
        "prior_strength": max(0, safe_float(request.form.get("bayesian_prior_strength"), BAYESIAN_DEFAULTS["prior_strength"])),
        "decay_rate": max(0, safe_float(request.form.get("bayesian_decay_rate"), BAYESIAN_DEFAULTS["decay_rate"])),
        "use_recency": request.form.get("bayesian_use_recency") == "1",
    }
    filter_params = {
        "score_source": request.form.get("score_source", GRIND_FILTER_DEFAULTS["score_source"]),
        "match_recipe": request.form.get("match_recipe") == "1",
        "temp_tolerance": max(0.5, safe_float(request.form.get("temp_tolerance"), GRIND_FILTER_DEFAULTS["temp_tolerance"])),
        "dose_tolerance": max(0.5, safe_float(request.form.get("dose_tolerance"), GRIND_FILTER_DEFAULTS["dose_tolerance"])),
        "finer_is_lower": request.form.get("finer_is_lower") != "0",
    }
    if filter_params["score_source"] not in SCORE_SOURCES:
        filter_params["score_source"] = "overall"

    with get_db() as conn:
        set_setting(conn, "grind_algorithm", algo)
        set_setting(conn, "grind_centroid_params", json.dumps(centroid_params))
        set_setting(conn, "grind_bayesian_params", json.dumps(bayesian_params))
        set_setting(conn, "grind_filter_params", json.dumps(filter_params))

    if request.headers.get("X-Auto-Save"):
        return jsonify({"ok": True})
    return redirect(url_for("settings_grind", saved="1"))


@app.route("/api/grind-preview", methods=["POST"])
def api_grind_preview():
    """Run grind suggestion on example scenario data (for settings preview).

    Accepts JSON with scenario shots and current settings, creates a
    temporary in-memory coffee + samples + evaluations, runs the real
    algorithm, and returns the result.
    """
    data = request.get_json(silent=True) or {}
    shots = data.get("shots", [])
    algo = data.get("algorithm", "weighted_centroid")
    centroid_p = data.get("centroid_params", {})
    bayesian_p = data.get("bayesian_params", {})
    filter_p = data.get("filter_params", {})

    if not shots:
        return jsonify({"error": "No shots provided"})

    # Build a temporary in-memory database with the scenario data
    mem = sqlite3.connect(":memory:")
    mem.row_factory = sqlite3.Row
    mem.execute("CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT)")
    mem.execute("CREATE TABLE coffees (id INTEGER PRIMARY KEY, label TEXT, default_grams_out REAL, process TEXT, bean_color TEXT)")
    mem.execute("""CREATE TABLE samples (
        id INTEGER PRIMARY KEY, coffee_id INTEGER, grind_size REAL,
        grams_in REAL, grams_out REAL, brew_time_sec INTEGER,
        brew_temp_c REAL, created_at TIMESTAMP)""")
    mem.execute("""CREATE TABLE evaluations (
        id INTEGER PRIMARY KEY, sample_id INTEGER UNIQUE,
        aroma INTEGER, acidity INTEGER, sweetness INTEGER,
        body INTEGER, balance INTEGER, overall INTEGER,
        created_at TIMESTAMP)""")

    target_out = data.get("target_output", 36)
    mem.execute("INSERT INTO coffees (id, label, default_grams_out) VALUES (1, 'Preview', ?)", (target_out,))

    for i, s in enumerate(shots):
        days_ago = s.get("daysAgo", 0)
        ts = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")
        mem.execute(
            "INSERT INTO samples (id, coffee_id, grind_size, grams_in, grams_out, brew_time_sec, brew_temp_c, created_at) VALUES (?,1,?,?,?,?,?,?)",
            (i + 1, s.get("grind", 18), s.get("dose", 18), s.get("output", 36),
             s.get("time", 28), s.get("temp", 91), ts),
        )
        score = s.get("score", 3)
        mem.execute(
            "INSERT INTO evaluations (sample_id, aroma, acidity, sweetness, body, balance, overall, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (i + 1, score, score, score, score, score, score, ts),
        )

    # Write settings into the in-memory DB
    set_setting(mem, "grind_algorithm", algo)
    set_setting(mem, "grind_centroid_params", json.dumps(centroid_p))
    set_setting(mem, "grind_bayesian_params", json.dumps(bayesian_p))
    set_setting(mem, "grind_filter_params", json.dumps(filter_p))

    try:
        result = suggest_grind(1, mem)
    finally:
        mem.close()

    if result is None:
        return jsonify({"grind": None, "confidence": "low", "detail": "Not enough data"})
    return jsonify(result)


# --- API ---

@app.route("/api/autocomplete")
def api_autocomplete():
    """Return unique values per field from existing coffees for autocomplete."""
    result = {}
    with get_db() as conn:
        for f in AUTOCOMPLETE_FIELDS:
            rows = conn.execute(
                f"SELECT DISTINCT {f} FROM coffees WHERE {f} IS NOT NULL AND {f} != '' ORDER BY {f}"
            ).fetchall()
            result[f] = [r[0] for r in rows]
    return jsonify(result)


@app.route("/api/coffees")
def api_coffees():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM coffees ORDER BY created_at DESC").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/samples")
def api_samples():
    with get_db() as conn:
        samples = conn.execute(
            """SELECT s.*, c.label as coffee_label,
                      e.aroma, e.acidity, e.sweetness, e.body, e.balance, e.overall
               FROM samples s
               JOIN coffees c ON s.coffee_id = c.id
               LEFT JOIN evaluations e ON e.sample_id = s.id
               ORDER BY s.created_at DESC"""
        ).fetchall()
    return jsonify([dict(s) for s in samples])


@app.route("/quit", methods=["POST"])
def quit_app():
    """Kill Chromium kiosk to return to desktop."""
    subprocess.Popen(["pkill", "-f", "chromium.*kiosk"])
    return "<html><body style='background:#1a1a1a;color:#e8e0d6;display:flex;align-items:center;justify-content:center;height:100vh;font-family:sans-serif'><h2>App closed.</h2></body></html>"


if __name__ == "__main__":
    init_db()
    backup_db()
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=5000, debug=debug)
