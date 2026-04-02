import sqlite3
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, jsonify

DB_PATH = Path(__file__).parent / "coffee.db"

app = Flask(__name__)

EVAL_DIMENSIONS = [
    {"key": "aroma", "label": "Aroma", "low": "None", "high": "Complex"},
    {"key": "acidity", "label": "Acidity", "low": "Flat", "high": "Bright"},
    {"key": "sweetness", "label": "Sweetness", "low": "Absent", "high": "Rich"},
    {"key": "body", "label": "Body", "low": "Thin", "high": "Full"},
    {"key": "balance", "label": "Balance", "low": "Poor", "high": "Integrated"},
    {"key": "overall", "label": "Overall", "low": "Bad", "high": "Excellent"},
]


def get_db():
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # migrate existing DBs missing updated_at
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(coffees)").fetchall()]
        if "updated_at" not in cols:
            conn.execute("ALTER TABLE coffees ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                coffee_id INTEGER NOT NULL REFERENCES coffees(id),
                grind_size REAL NOT NULL,
                grams_in REAL NOT NULL,
                grams_out REAL NOT NULL,
                brew_time_sec INTEGER NOT NULL,
                ratio REAL GENERATED ALWAYS AS (grams_out / NULLIF(grams_in, 0)) STORED,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


def make_label(data):
    parts = [data.get("roaster", ""), data.get("variety", ""), data.get("process", "")]
    label = " - ".join(p.strip() for p in parts if p and p.strip())
    return label or "Unnamed Coffee"


def diagnose(ev):
    """Return diagnostic tips based on evaluation scores."""
    tips = []
    acidity = ev.get("acidity", 3)
    sweetness = ev.get("sweetness", 3)
    body = ev.get("body", 3)

    if acidity >= 4 and sweetness <= 2 and body <= 2:
        tips.append("Likely under-extracted. Try grinding finer or extending brew time.")
    elif acidity >= 4 and sweetness <= 2:
        tips.append("High acidity, low sweetness — try grinding a touch finer.")
    elif acidity <= 2 and sweetness <= 2:
        tips.append("Likely over-extracted. Try grinding coarser or shorter brew time.")
    elif body <= 2 and sweetness >= 3:
        tips.append("Thin body — try increasing dose or grinding slightly finer.")

    if ev.get("balance", 3) >= 4 and ev.get("overall", 3) >= 4:
        tips.append("Great shot! Save this recipe as a reference.")
    elif not tips:
        if ev.get("overall", 3) >= 4:
            tips.append("Solid shot. Minor tweaks could make it even better.")

    return tips


# --- Step 1: Select or define coffee ---

@app.route("/")
def index():
    with get_db() as conn:
        coffees = conn.execute(
            "SELECT * FROM coffees ORDER BY created_at DESC"
        ).fetchall()
    return render_template("step1_coffee.html", coffees=coffees)


@app.route("/coffee/add", methods=["POST"])
def add_coffee():
    data = request.form
    label = data.get("label", "").strip() or make_label(data)
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO coffees (roaster, origin_country, origin_city, origin_producer,
                                    variety, process, tasting_notes, label, roast_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data.get("roaster", "").strip() or None,
                data.get("origin_country", "").strip() or None,
                data.get("origin_city", "").strip() or None,
                data.get("origin_producer", "").strip() or None,
                data.get("variety", "").strip() or None,
                data.get("process", "").strip() or None,
                data.get("tasting_notes", "").strip() or None,
                label,
                data.get("roast_date", "").strip() or None,
            ),
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
    data = request.form
    label = data.get("label", "").strip() or make_label(data)
    with get_db() as conn:
        conn.execute(
            """UPDATE coffees SET roaster=?, origin_country=?, origin_city=?, origin_producer=?,
                                  variety=?, process=?, tasting_notes=?, label=?, roast_date=?,
                                  updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (
                data.get("roaster", "").strip() or None,
                data.get("origin_country", "").strip() or None,
                data.get("origin_city", "").strip() or None,
                data.get("origin_producer", "").strip() or None,
                data.get("variety", "").strip() or None,
                data.get("process", "").strip() or None,
                data.get("tasting_notes", "").strip() or None,
                label,
                data.get("roast_date", "").strip() or None,
                coffee_id,
            ),
        )
    return redirect(url_for("new_sample", coffee_id=coffee_id))


@app.route("/coffee/<int:coffee_id>/delete", methods=["POST"])
def delete_coffee(coffee_id):
    with get_db() as conn:
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
    return render_template("step2_sample.html", coffee=coffee, samples=samples)


@app.route("/sample/<int:coffee_id>/add", methods=["POST"])
def add_sample(coffee_id):
    data = request.form
    minutes = int(data.get("brew_min", 0) or 0)
    seconds = int(data.get("brew_sec", 0) or 0)
    brew_time_sec = minutes * 60 + seconds

    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO samples (coffee_id, grind_size, grams_in, grams_out, brew_time_sec, notes)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                coffee_id,
                float(data["grind_size"]),
                float(data["grams_in"]),
                float(data["grams_out"]),
                brew_time_sec,
                data.get("notes", ""),
            ),
        )
        sample_id = cur.lastrowid
    return redirect(url_for("evaluate_sample", sample_id=sample_id))


@app.route("/sample/<int:sample_id>/delete", methods=["POST"])
def delete_sample(sample_id):
    with get_db() as conn:
        row = conn.execute("SELECT coffee_id FROM samples WHERE id = ?", (sample_id,)).fetchone()
        conn.execute("DELETE FROM evaluations WHERE sample_id = ?", (sample_id,))
        conn.execute("DELETE FROM samples WHERE id = ?", (sample_id,))
    if row:
        return redirect(url_for("new_sample", coffee_id=row["coffee_id"]))
    return redirect(url_for("index"))


# --- Step 3: Evaluate a sample ---

@app.route("/evaluate/<int:sample_id>")
def evaluate_sample(sample_id):
    with get_db() as conn:
        sample = conn.execute("SELECT * FROM samples WHERE id = ?", (sample_id,)).fetchone()
        if not sample:
            return redirect(url_for("index"))
        coffee = conn.execute("SELECT * FROM coffees WHERE id = ?", (sample["coffee_id"],)).fetchone()
        existing = conn.execute("SELECT * FROM evaluations WHERE sample_id = ?", (sample_id,)).fetchone()
    return render_template(
        "step3_evaluate.html",
        coffee=coffee, sample=sample, evaluation=existing,
        dimensions=EVAL_DIMENSIONS, tips=None,
    )


@app.route("/evaluate/<int:sample_id>/save", methods=["POST"])
def save_evaluation(sample_id):
    data = request.form
    scores = {}
    for dim in EVAL_DIMENSIONS:
        val = data.get(dim["key"])
        scores[dim["key"]] = int(val) if val else None

    with get_db() as conn:
        sample = conn.execute("SELECT * FROM samples WHERE id = ?", (sample_id,)).fetchone()
        if not sample:
            return redirect(url_for("index"))
        coffee = conn.execute("SELECT * FROM coffees WHERE id = ?", (sample["coffee_id"],)).fetchone()

        existing = conn.execute("SELECT id FROM evaluations WHERE sample_id = ?", (sample_id,)).fetchone()
        if existing:
            conn.execute(
                """UPDATE evaluations SET aroma=?, acidity=?, sweetness=?, body=?, balance=?, overall=?
                   WHERE sample_id=?""",
                (scores["aroma"], scores["acidity"], scores["sweetness"],
                 scores["body"], scores["balance"], scores["overall"], sample_id),
            )
        else:
            conn.execute(
                """INSERT INTO evaluations (sample_id, aroma, acidity, sweetness, body, balance, overall)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (sample_id, scores["aroma"], scores["acidity"], scores["sweetness"],
                 scores["body"], scores["balance"], scores["overall"]),
            )

        evaluation = conn.execute("SELECT * FROM evaluations WHERE sample_id = ?", (sample_id,)).fetchone()

    tips = diagnose(scores)
    return render_template(
        "step3_evaluate.html",
        coffee=coffee, sample=sample, evaluation=evaluation,
        dimensions=EVAL_DIMENSIONS, tips=tips,
    )


# --- API ---

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


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
