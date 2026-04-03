import json
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
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or os.urandom(32)

CACHE_BUST = str(int(time.time()))


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


# Column allowlists for undo route (SQL injection prevention)
COFFEE_COLUMNS = {"roaster", "origin_country", "origin_city", "origin_producer",
                  "variety", "process", "tasting_notes", "label", "roast_date",
                  "best_after_days", "consume_within_days", "bag_weight_g", "bag_price",
                  "default_grams_in", "default_grams_out", "default_brew_time_sec",
                  "bean_color", "bean_size", "opened_date",
                  "archived", "created_at", "updated_at"}
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
                                  "origin_producer", "variety", "process"])

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
    "Dry", "Astringent", "Thin", "Flat", "Harsh",
]

# =============================================================================
# Sections: backup_db, init_db, helpers, routes (coffee → sample → evaluate →
# stats → settings → API → quit)
# =============================================================================


def backup_db():
    """Create a daily backup of coffee.db. Prune backups older than BACKUP_MAX_DAYS."""
    BACKUP_DIR.mkdir(exist_ok=True)
    today = date.today().isoformat()
    backup_file = BACKUP_DIR / f"coffee-{today}.db"
    if not backup_file.exists() and DB_PATH.exists():
        shutil.copy2(DB_PATH, backup_file)
    # Prune old backups
    cutoff = datetime.now() - timedelta(days=BACKUP_MAX_DAYS)
    for f in BACKUP_DIR.glob("coffee-*.db"):
        try:
            fdate = datetime.strptime(f.stem.replace("coffee-", ""), "%Y-%m-%d")
            if fdate < cutoff:
                f.unlink()
        except ValueError:
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


# IMPORTANT: This dict must stay in sync with the NOTES object in
# static/tastingnotes.js. Future: generate one from the other via shared JSON.
TASTING_EMOJIS = {
    "dried apricot": "🍑", "apricot": "🍑", "lemonade": "🍋", "lemon": "🍋",
    "orange": "🍊", "tangerine": "🍊", "black currant": "🫐", "blueberry": "🫐",
    "strawberry": "🍓", "wild strawberry": "🍓", "raspberry": "🍓",
    "raspberry jam": "🍓", "cherry": "🍒", "apple": "🍏", "peach": "🍑",
    "plum": "🍇", "grape": "🍇", "tropical": "🍍", "pineapple": "🍍",
    "mango": "🥭", "passionfruit": "🍈", "melon": "🍈", "banana": "🍌",
    "grapefruit": "🍊", "lime": "🍋", "citrus": "🍋", "bergamot": "🍋",
    "cacao nibs": "🍫", "chocolate": "🍫", "dark chocolate": "🍫", "cocoa": "🍫",
    "hazelnut": "🌰", "almond": "🌰", "walnut": "🌰", "nutty": "🌰",
    "honey": "🍯", "caramel": "🍮", "toffee": "🍮", "brown sugar": "🍮",
    "vanilla": "🍦", "jasmine": "🌸", "rose": "🌹", "floral": "🌺",
    "hibiscus": "🌺", "tea": "🍵", "black tea": "🍵", "herbal": "🌿",
    "mint": "🌿", "cinnamon": "✨", "cardamom": "✨", "ginger": "✨",
    "pepper": "🌶️", "smoky": "🔥", "tobacco": "🍂", "wine": "🍷",
    "red wine": "🍷", "butter": "🧈", "cream": "🥛", "cedar": "🪵",
    "woody": "🪵", "earthy": "🌍", "berry": "🫐", "stone fruit": "🍑",
    "nougat": "🍮",
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


def freshness_status(coffee):
    """Compute freshness status from roast_date, best_after_days, consume_within_days.

    Stages based on specialty coffee research (SCA, WBC consensus):
    - Degassing (day 0-2): high CO2, shots unstable/sour
    - Resting (day 3 to best_after): CO2 releasing, flavor developing
    - Peak (best_after to best_after+11): origin character vibrant, crema rich
    - Good (to best_after+25): some volatiles fading, still pleasant
    - Fading (to consume_within): noticeably flat, papery notes emerging
    - Stale (beyond consume_within): cardboard/musty, not recommended
    """
    if not coffee["roast_date"]:
        return None
    try:
        roast = datetime.strptime(coffee["roast_date"], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None

    days = (date.today() - roast).days
    best_after = coffee["best_after_days"] or 7
    consume_within = coffee["consume_within_days"] or 50

    # Stage boundaries
    degas_end = min(3, best_after)        # first 3 days: heavy CO2
    rest_end = best_after                 # resting until best_after
    peak_end = best_after + 11            # ~11 days of peak after rest
    good_end = best_after + 25            # ~3.5 weeks still good
    fading_end = consume_within

    if days < 0:
        return {"stage": "not roasted yet", "css": "fresh-future", "days": days,
                "detail": f"Roast date is {-days} days from now"}
    elif days < degas_end:
        return {"stage": "degassing", "css": "fresh-degas", "days": days,
                "detail": f"High CO2 — shots will be sour and unstable (day {days})"}
    elif days < rest_end:
        remaining = rest_end - days
        return {"stage": "resting", "css": "fresh-rest", "days": days,
                "detail": f"Almost ready — {remaining} more day{'s' if remaining != 1 else ''} to go"}
    elif days <= peak_end:
        return {"stage": "peak", "css": "fresh-peak", "days": days,
                "detail": f"Peak flavor window (day {days})"}
    elif days <= good_end:
        remaining = good_end - days
        return {"stage": "good", "css": "fresh-good", "days": days,
                "detail": f"Still great — {remaining} days of prime left"}
    elif days <= fading_end:
        remaining = fading_end - days
        return {"stage": "fading", "css": "fresh-fading", "days": days,
                "detail": f"Fading — use within {remaining} days"}
    else:
        over = days - fading_end
        return {"stage": "stale", "css": "fresh-stale", "days": days,
                "detail": f"Past prime by {over} day{'s' if over != 1 else ''}"}


def diagnose(ev, taste_desc=None, actual_out=None, target_out=None, brew_time=None):
    """Return diagnostic tips based on scores, taste descriptors, output deviation, and brew time."""
    tips = []
    acidity = ev.get("acidity", 3)
    sweetness = ev.get("sweetness", 3)
    body = ev.get("body", 3)
    taste_tags = set(t.strip().lower() for t in (taste_desc or "").split(",") if t.strip())

    # Taste descriptor-based diagnostics (work even with 0 prior shots)
    under_signs = taste_tags & {"sour", "acidic", "thin", "flat"}
    over_signs = taste_tags & {"bitter", "burned", "ashy", "dry", "astringent", "harsh"}

    if under_signs and over_signs:
        tips.append("Sour AND bitter — likely channeling. Fix puck prep first: use WDT, distribute evenly, tamp consistently. Don't adjust grind until prep is consistent.")
    elif len(under_signs) >= 3 or (len(under_signs) >= 2 and acidity >= 4):
        tips.append(f"Strongly under-extracted ({', '.join(under_signs)}). Grind significantly finer (2-3 steps).")
    elif under_signs:
        tips.append(f"Under-extracted ({', '.join(under_signs)}). Grind a little finer (1 step).")
    elif len(over_signs) >= 3 or (len(over_signs) >= 2 and sweetness <= 2):
        tips.append(f"Strongly over-extracted ({', '.join(over_signs)}). Grind significantly coarser (2-3 steps).")
    elif over_signs:
        tips.append(f"Over-extracted ({', '.join(over_signs)}). Grind a little coarser (1 step).")

    # Score-based diagnostics (fallback when no taste descriptors selected)
    if not tips:
        if acidity >= 4 and sweetness <= 2 and body <= 2:
            tips.append("Likely under-extracted. Try grinding somewhat finer (1-2 steps).")
        elif acidity >= 4 and sweetness <= 2:
            tips.append("High acidity, low sweetness — try grinding a little finer (1 step).")
        elif acidity <= 2 and sweetness <= 2:
            tips.append("Likely over-extracted. Try grinding a little coarser (1 step).")
        elif body <= 2 and sweetness >= 3:
            tips.append("Thin body — try increasing dose or grinding slightly finer.")

    # Brew time diagnostic
    if brew_time:
        if brew_time < 20:
            tips.append(f"Very fast shot ({brew_time}s). Target is 25-30s — grind much finer.")
        elif brew_time < 25 and under_signs:
            tips.append(f"Fast shot ({brew_time}s) confirms under-extraction — grind finer.")
        elif brew_time > 35:
            tips.append(f"Very slow shot ({brew_time}s). Target is 25-30s — grind coarser or check for choke.")
        elif brew_time > 30 and over_signs:
            tips.append(f"Slow shot ({brew_time}s) confirms over-extraction — grind coarser.")

    # Output deviation diagnostic (granular thresholds from research)
    if actual_out and target_out and target_out > 0:
        dev_g = actual_out - target_out
        if dev_g > 10:
            tips.append(f"Output +{dev_g:.0f}g over target — severe. Check for channeling, grind much finer.")
        elif dev_g > 5:
            tips.append(f"Output +{dev_g:.0f}g over target — grind finer (2 steps) and check distribution.")
        elif dev_g > 2:
            tips.append(f"Output +{dev_g:.0f}g over target — grind a little finer (1 step).")
        elif dev_g < -10:
            tips.append(f"Output {dev_g:.0f}g under target — severely choked. Grind much coarser.")
        elif dev_g < -5:
            tips.append(f"Output {dev_g:.0f}g under target — grind coarser (2 steps), check tamp pressure.")
        elif dev_g < -2:
            tips.append(f"Output {dev_g:.0f}g under target — grind a little coarser (1 step).")

    # Positive feedback
    if ev.get("balance", 3) >= 4 and ev.get("overall", 3) >= 4:
        tips.append("Great shot! Save this recipe as a reference.")
    elif not tips:
        if ev.get("overall", 3) >= 4:
            tips.append("Solid shot. Minor tweaks could make it even better.")

    return tips


def coffee_rating(coffee_id, conn):
    """Compute aggregate rating from representative evaluated shots for a coffee."""
    rows = conn.execute(
        """SELECT e.aroma, e.acidity, e.sweetness, e.body, e.balance, e.overall
           FROM evaluations e JOIN samples s ON e.sample_id = s.id
           WHERE s.coffee_id = ? AND e.representative = 1
             AND e.aroma IS NOT NULL""",
        (coffee_id,),
    ).fetchall()

    if not rows:
        return None

    dims = ["aroma", "acidity", "sweetness", "body", "balance"]
    totals = {d: 0 for d in dims}
    overall_sum = 0
    for r in rows:
        for d in dims:
            totals[d] += r[d] or 0
        overall_sum += r["overall"] or 0
    n = len(rows)
    avgs = {d: totals[d] / n for d in dims}
    avg_overall = overall_sum / n
    avg_taste = sum(avgs.values()) / len(dims)

    # Flavor profile descriptor
    descriptors = []
    if avgs["acidity"] >= 3.5:
        descriptors.append("Bright")
    elif avgs["acidity"] <= 2:
        descriptors.append("Mellow")
    if avgs["sweetness"] >= 3.5:
        descriptors.append("Sweet")
    if avgs["body"] >= 3.5:
        descriptors.append("Full-bodied")
    elif avgs["body"] <= 2:
        descriptors.append("Light")
    if avgs["balance"] >= 4:
        descriptors.append("Well-balanced")
    if avgs["aroma"] >= 4:
        descriptors.append("Aromatic")

    # Rating tier based on average taste score (1-5)
    if avg_taste >= 4.5:
        tier = "Outstanding"
        css = "tier-outstanding"
    elif avg_taste >= 3.8:
        tier = "Excellent"
        css = "tier-excellent"
    elif avg_taste >= 3.0:
        tier = "Very Good"
        css = "tier-verygood"
    elif avg_taste >= 2.2:
        tier = "Good"
        css = "tier-good"
    else:
        tier = "Below Average"
        css = "tier-below"

    profile = ", ".join(descriptors) if descriptors else "Neutral profile"

    return {
        "tier": tier,
        "css": css,
        "avg_taste": round(avg_taste, 1),
        "avg_overall": round(avg_overall, 1),
        "profile": profile,
        "avgs": {d: round(avgs[d], 1) for d in dims},
        "n": n,
    }


def suggest_grind(coffee_id, conn):
    """Suggest optimal grind size using quadratic regression on past evaluated shots."""
    rows = conn.execute(
        """SELECT s.grind_size, e.overall
           FROM samples s JOIN evaluations e ON e.sample_id = s.id
           WHERE s.coffee_id = ? AND e.overall IS NOT NULL
           ORDER BY s.created_at""",
        (coffee_id,),
    ).fetchall()

    if len(rows) < 3:
        # Not enough data for regression — return best shot's grind if any
        if rows:
            best = max(rows, key=lambda r: r["overall"])
            return {
                "grind": best["grind_size"],
                "confidence": "low",
                "detail": f"Best so far: grind {best['grind_size']} scored {best['overall']}/5 ({len(rows)} shot{'s' if len(rows) != 1 else ''} evaluated)",
            }
        return None

    if np is None:
        best = max(rows, key=lambda r: r["overall"])
        return {"grind": best["grind_size"], "confidence": "low",
                "detail": f"Best so far: grind {best['grind_size']} ({best['overall']}/5) — numpy not available"}

    grinds = np.array([r["grind_size"] for r in rows], dtype=float)
    scores = np.array([r["overall"] for r in rows], dtype=float)

    try:
        coeffs = np.polyfit(grinds, scores, 2)
    except (np.linalg.LinAlgError, ValueError):
        best = max(rows, key=lambda r: r["overall"])
        return {
            "grind": best["grind_size"],
            "confidence": "low",
            "detail": f"Best so far: grind {best['grind_size']} scored {best['overall']}/5",
        }

    a, b, c = coeffs

    # Quadratic must open downward (a < 0) for a maximum
    if a >= 0:
        best = max(rows, key=lambda r: r["overall"])
        return {
            "grind": best["grind_size"],
            "confidence": "low",
            "detail": f"No clear peak yet — best: grind {best['grind_size']} ({best['overall']}/5)",
        }

    optimal = -b / (2 * a)
    predicted = a * optimal**2 + b * optimal + c
    gmin, gmax = float(grinds.min()), float(grinds.max())

    if optimal < gmin - 5 or optimal > gmax + 5:
        direction = "finer" if optimal < gmin else "coarser"
        return {
            "grind": round(optimal, 1),
            "confidence": "low",
            "detail": f"Model suggests going {direction} (grind ~{optimal:.1f}) — try extending your range",
        }

    n = len(rows)
    conf = "medium" if n < 6 else "high"
    best_actual = max(rows, key=lambda r: r["overall"])

    return {
        "grind": round(optimal, 1),
        "confidence": conf,
        "detail": f"Suggested grind: {optimal:.1f} (predicted {predicted:.1f}/5 from {n} shots, best actual: {best_actual['grind_size']} → {best_actual['overall']}/5)",
    }


# --- Step 1: Select or define coffee ---

@app.route("/")
def index():
    show_archived = request.args.get("archived") == "1"
    with get_db() as conn:
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
            # Compute days since opened
            cd["days_open"] = None
            if c["opened_date"]:
                try:
                    opened = datetime.strptime(c["opened_date"], "%Y-%m-%d").date()
                    cd["days_open"] = (date.today() - opened).days
                except (ValueError, TypeError):
                    pass
            if c["bag_weight_g"]:
                cd["grams_left"] = max(0, c["bag_weight_g"] - cd["grams_used"])
            else:
                cd["grams_left"] = None
            coffee_data.append(cd)
    return render_template("step1_coffee.html", coffees=coffee_data, show_archived=show_archived)


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
        "best_after_days": safe_int(best_after, 7),
        "consume_within_days": safe_int(consume_within, 50),
        "bag_weight_g": safe_float(bag_weight),
        "bag_price": safe_float(bag_price),
        "default_grams_in": safe_float(data.get("default_grams_in", "").strip()),
        "default_grams_out": safe_float(data.get("default_grams_out", "").strip()),
        "default_brew_time_sec": def_time,
        "bean_color": data.get("bean_color", "").strip() or None,
        "bean_size": data.get("bean_size", "").strip() or None,
        "opened_date": data.get("opened_date", "").strip() or None,
    }


@app.route("/coffee/add", methods=["POST"])
def add_coffee():
    fields = parse_coffee_form(request.form)
    # Guard against SQL injection from unexpected columns
    assert all(c in COFFEE_COLUMNS for c in fields.keys()), "Invalid column in form fields"
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
    assert all(c in COFFEE_COLUMNS for c in fields.keys()), "Invalid column in form fields"
    set_clause = ", ".join(f"{c}=?" for c in fields.keys())
    with get_db() as conn:
        conn.execute(
            f"UPDATE coffees SET {set_clause}, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            list(fields.values()) + [coffee_id],
        )
    return redirect(url_for("new_sample", coffee_id=coffee_id))


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
    grind_hint = None
    with get_db() as conn:
        grind_hint = suggest_grind(coffee_id, conn)
    # Compute days since opened
    days_open = None
    if coffee["opened_date"]:
        try:
            days_open = (date.today() - datetime.strptime(coffee["opened_date"], "%Y-%m-%d").date()).days
        except (ValueError, TypeError):
            pass
    return render_template("step2_sample.html", coffee=coffee, samples=samples,
                           freshness=freshness, grind_hint=grind_hint, days_open=days_open)


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

    with get_db() as conn:
        # Compute days since roast and since opened
        coffee = conn.execute("SELECT roast_date, opened_date FROM coffees WHERE id = ?", (coffee_id,)).fetchone()
        days_since_roast = None
        days_since_opened = None
        today = date.today()
        if coffee:
            if coffee["roast_date"]:
                try:
                    days_since_roast = (today - datetime.strptime(coffee["roast_date"], "%Y-%m-%d").date()).days
                except (ValueError, TypeError):
                    pass
            if coffee["opened_date"]:
                try:
                    days_since_opened = (today - datetime.strptime(coffee["opened_date"], "%Y-%m-%d").date()).days
                except (ValueError, TypeError):
                    pass

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
    return redirect(url_for("evaluate_sample", sample_id=sample_id))


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
    return render_template("edit_sample.html", sample=sample, coffee=coffee, all_coffees=all_coffees)


@app.route("/sample/<int:sample_id>/edit", methods=["POST"])
def save_sample(sample_id):
    """Save edited sample brew parameters and/or move to different coffee."""
    data = request.form
    new_coffee_id = safe_int(data.get("coffee_id"))
    with get_db() as conn:
        sample = conn.execute("SELECT * FROM samples WHERE id = ?", (sample_id,)).fetchone()
        if not sample:
            return redirect(url_for("index"))
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

        # All coffees for cross-coffee insights
        all_coffees = conn.execute("SELECT id, label, process FROM coffees WHERE archived = 0").fetchall()
        cross_data = []
        for ac in all_coffees:
            best = conn.execute(
                """SELECT s.grind_size, e.overall FROM samples s JOIN evaluations e ON e.sample_id = s.id
                   WHERE s.coffee_id = ? AND e.overall IS NOT NULL ORDER BY e.overall DESC LIMIT 1""",
                (ac["id"],),
            ).fetchone()
            if best:
                cross_data.append({"label": ac["label"], "process": ac["process"] or "?",
                                   "grind": best["grind_size"], "score": best["overall"]})

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

    # Compute days since opened
    days_open = None
    if coffee["opened_date"]:
        try:
            days_open = (date.today() - datetime.strptime(coffee["opened_date"], "%Y-%m-%d").date()).days
        except (ValueError, TypeError):
            pass

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
        # Get last grind_aroma for pre-fill
        last_aroma = conn.execute(
            """SELECT e.grind_aroma FROM evaluations e JOIN samples s ON e.sample_id = s.id
               WHERE s.coffee_id = ? AND e.grind_aroma IS NOT NULL
               ORDER BY e.created_at DESC LIMIT 1""",
            (sample["coffee_id"],),
        ).fetchone()
    freshness = freshness_status(coffee)
    prefill_grind_aroma = last_aroma["grind_aroma"] if last_aroma else None
    return render_template(
        "step3_evaluate.html",
        coffee=coffee, sample=sample, evaluation=existing,
        dimensions=EVAL_DIMENSIONS, tips=None, freshness=freshness,
        prefill_grind_aroma=prefill_grind_aroma,
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
        prefill_grind_aroma=None,
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
