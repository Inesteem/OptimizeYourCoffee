"""
Tests for the Coffee Sampler Flask app (coffee-app/app.py).

Run with:
    python3.11 -m pytest tests/        (from project root)
    pytest tests/                      (if pytest resolves to python3.11's pytest)
"""

import json
import os
import sqlite3
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Path setup — make the coffee-app package importable without installing it
# ---------------------------------------------------------------------------
APP_DIR = Path(__file__).resolve().parents[1] / "coffee-app"
sys.path.insert(0, str(APP_DIR))

import app as coffee_app  # noqa: E402  (import after sys.path manipulation)
from app import (  # noqa: E402
    make_label,
    freshness_status,
    diagnose,
    suggest_grind,
    coffee_rating,
    render_tasting_notes,
    init_db,
    get_setting,
    set_setting,
    TASTING_EMOJIS,
    CENTROID_DEFAULTS,
    BAYESIAN_DEFAULTS,
    _suggest_grind_quadratic,
    _suggest_grind_centroid,
    _suggest_grind_bayesian,
    _suggest_grind_ratio,
    _extract_score,
    _grind_rows,
    _cross_coffee_prior,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_coffee_row(**kwargs):
    """Return a dict that behaves like a sqlite3.Row for freshness_status / coffee_rating."""
    defaults = {
        "roast_date": None,
        "best_after_days": 7,
        "consume_within_days": 50,
    }
    defaults.update(kwargs)
    return defaults


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """
    Replace the app's DB_PATH with a fresh temp-file database and re-initialise it.
    Returns the path so tests can open it directly when needed.
    """
    db_file = tmp_path / "test_coffee.db"
    monkeypatch.setattr(coffee_app, "DB_PATH", db_file)
    init_db()
    return db_file


@pytest.fixture()
def client(tmp_db):
    """Flask test client wired to the temp database."""
    coffee_app.app.config["TESTING"] = True
    coffee_app.app.config["WTF_CSRF_ENABLED"] = False
    with coffee_app.app.test_client() as c:
        yield c


def _add_coffee(client, **overrides):
    """POST /coffee/add with sensible defaults; return the redirect location."""
    data = {
        "roaster": "Test Roaster",
        "variety": "Bourbon",
        "process": "Washed",
        "label": "",
        "roast_date": "2025-01-01",
        "best_after_days": "7",
        "consume_within_days": "50",
    }
    data.update(overrides)
    resp = client.post("/coffee/add", data=data)
    return resp


def _get_db(tmp_db):
    conn = sqlite3.connect(tmp_db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ===========================================================================
# 1. DATABASE OPERATIONS
# ===========================================================================

class TestInitDb:
    def test_creates_coffees_table(self, tmp_db):
        conn = _get_db(tmp_db)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "coffees" in tables

    def test_creates_samples_table(self, tmp_db):
        conn = _get_db(tmp_db)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "samples" in tables

    def test_creates_evaluations_table(self, tmp_db):
        conn = _get_db(tmp_db)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "evaluations" in tables

    def test_creates_custom_tasting_notes_table(self, tmp_db):
        conn = _get_db(tmp_db)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "custom_tasting_notes" in tables

    def test_coffees_has_archived_column(self, tmp_db):
        conn = _get_db(tmp_db)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(coffees)").fetchall()}
        assert "archived" in cols

    def test_evaluations_has_representative_column(self, tmp_db):
        conn = _get_db(tmp_db)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(evaluations)").fetchall()}
        assert "representative" in cols

    def test_init_db_is_idempotent(self, tmp_db):
        """Calling init_db a second time must not raise or corrupt the DB."""
        init_db()
        conn = _get_db(tmp_db)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert {"coffees", "samples", "evaluations", "custom_tasting_notes"}.issubset(tables)


class TestAddCoffee:
    def test_add_coffee_redirects(self, client):
        resp = _add_coffee(client)
        assert resp.status_code == 302

    def test_add_coffee_creates_record(self, client, tmp_db):
        _add_coffee(client, roaster="Blue Bottle", variety="SL28", process="Natural")
        conn = _get_db(tmp_db)
        row = conn.execute("SELECT * FROM coffees WHERE roaster='Blue Bottle'").fetchone()
        assert row is not None
        assert row["variety"] == "SL28"
        assert row["process"] == "Natural"

    def test_add_coffee_autogenerates_label(self, client, tmp_db):
        _add_coffee(client, roaster="Onyx", variety="Typica", process="Honey", label="")
        conn = _get_db(tmp_db)
        row = conn.execute("SELECT * FROM coffees WHERE roaster='Onyx'").fetchone()
        assert row["label"] == "Onyx - Typica - Honey"

    def test_add_coffee_uses_provided_label(self, client, tmp_db):
        _add_coffee(client, roaster="Onyx", label="My Custom Label")
        conn = _get_db(tmp_db)
        row = conn.execute("SELECT * FROM coffees WHERE roaster='Onyx'").fetchone()
        assert row["label"] == "My Custom Label"

    def test_add_coffee_default_best_after_null(self, client, tmp_db):
        """Empty best_after_days stores NULL (roast-level default used at runtime)."""
        _add_coffee(client, best_after_days="")
        conn = _get_db(tmp_db)
        row = conn.execute("SELECT * FROM coffees ORDER BY id DESC LIMIT 1").fetchone()
        assert row["best_after_days"] is None

    def test_add_coffee_brew_time_combines_min_sec(self, client, tmp_db):
        _add_coffee(client, default_brew_min="1", default_brew_sec="30")
        conn = _get_db(tmp_db)
        row = conn.execute("SELECT * FROM coffees ORDER BY id DESC LIMIT 1").fetchone()
        assert row["default_brew_time_sec"] == 90


class TestAddSample:
    def _insert_coffee(self, tmp_db):
        conn = _get_db(tmp_db)
        cur = conn.execute(
            "INSERT INTO coffees (label) VALUES (?)", ("Test Coffee",)
        )
        conn.commit()
        return cur.lastrowid

    def test_add_sample_creates_record(self, client, tmp_db):
        coffee_id = self._insert_coffee(tmp_db)
        resp = client.post(f"/sample/{coffee_id}/add", data={
            "grind_size": "18.5",
            "grams_in": "18",
            "grams_out": "36",
            "brew_min": "0",
            "brew_sec": "28",
            "notes": "test shot",
        })
        assert resp.status_code == 302
        conn = _get_db(tmp_db)
        row = conn.execute("SELECT * FROM samples WHERE coffee_id=?", (coffee_id,)).fetchone()
        assert row is not None
        assert row["grind_size"] == 18.5
        assert row["grams_in"] == 18.0
        assert row["grams_out"] == 36.0
        assert row["brew_time_sec"] == 28

    def test_add_sample_redirects_to_evaluate(self, client, tmp_db):
        coffee_id = self._insert_coffee(tmp_db)
        resp = client.post(f"/sample/{coffee_id}/add", data={
            "grind_size": "18",
            "grams_in": "18",
            "grams_out": "36",
            "brew_min": "0",
            "brew_sec": "25",
        })
        assert "/evaluate/" in resp.headers["Location"]

    def test_add_sample_brew_time_with_minutes(self, client, tmp_db):
        coffee_id = self._insert_coffee(tmp_db)
        client.post(f"/sample/{coffee_id}/add", data={
            "grind_size": "20",
            "grams_in": "18",
            "grams_out": "36",
            "brew_min": "1",
            "brew_sec": "5",
        })
        conn = _get_db(tmp_db)
        row = conn.execute("SELECT * FROM samples WHERE coffee_id=?", (coffee_id,)).fetchone()
        assert row["brew_time_sec"] == 65


class TestAddEvaluation:
    def _seed(self, tmp_db):
        conn = _get_db(tmp_db)
        cur = conn.execute("INSERT INTO coffees (label) VALUES (?)", ("Eval Coffee",))
        coffee_id = cur.lastrowid
        cur2 = conn.execute(
            "INSERT INTO samples (coffee_id, grind_size, grams_in, grams_out, brew_time_sec) VALUES (?,?,?,?,?)",
            (coffee_id, 18, 18, 36, 28),
        )
        sample_id = cur2.lastrowid
        conn.commit()
        return coffee_id, sample_id

    def test_save_evaluation_creates_record(self, client, tmp_db):
        _, sample_id = self._seed(tmp_db)
        client.post(f"/evaluate/{sample_id}/save", data={
            "aroma": "4", "acidity": "3", "sweetness": "3",
            "body": "3", "balance": "4", "overall": "4",
        })
        conn = _get_db(tmp_db)
        row = conn.execute("SELECT * FROM evaluations WHERE sample_id=?", (sample_id,)).fetchone()
        assert row is not None
        assert row["aroma"] == 4
        assert row["overall"] == 4

    def test_save_evaluation_representative_flag(self, client, tmp_db):
        _, sample_id = self._seed(tmp_db)
        client.post(f"/evaluate/{sample_id}/save", data={
            "aroma": "5", "acidity": "4", "sweetness": "4",
            "body": "4", "balance": "5", "overall": "5",
            "representative": "1",
        })
        conn = _get_db(tmp_db)
        row = conn.execute("SELECT * FROM evaluations WHERE sample_id=?", (sample_id,)).fetchone()
        assert row["representative"] == 1

    def test_save_evaluation_not_representative_by_default(self, client, tmp_db):
        _, sample_id = self._seed(tmp_db)
        client.post(f"/evaluate/{sample_id}/save", data={
            "aroma": "3", "acidity": "3", "sweetness": "3",
            "body": "3", "balance": "3", "overall": "3",
        })
        conn = _get_db(tmp_db)
        row = conn.execute("SELECT * FROM evaluations WHERE sample_id=?", (sample_id,)).fetchone()
        assert row["representative"] == 0

    def test_save_evaluation_updates_existing(self, client, tmp_db):
        _, sample_id = self._seed(tmp_db)
        # First save
        client.post(f"/evaluate/{sample_id}/save", data={
            "aroma": "2", "acidity": "2", "sweetness": "2",
            "body": "2", "balance": "2", "overall": "2",
        })
        # Second save should update, not insert a duplicate
        client.post(f"/evaluate/{sample_id}/save", data={
            "aroma": "5", "acidity": "5", "sweetness": "5",
            "body": "5", "balance": "5", "overall": "5",
        })
        conn = _get_db(tmp_db)
        rows = conn.execute("SELECT * FROM evaluations WHERE sample_id=?", (sample_id,)).fetchall()
        assert len(rows) == 1
        assert rows[0]["overall"] == 5


class TestEditCoffee:
    def test_edit_coffee_updates_fields(self, client, tmp_db):
        _add_coffee(client, roaster="Old Roaster", variety="Caturra", process="Washed")
        conn = _get_db(tmp_db)
        coffee_id = conn.execute("SELECT id FROM coffees WHERE roaster='Old Roaster'").fetchone()["id"]

        client.post(f"/coffee/{coffee_id}/edit", data={
            "roaster": "New Roaster",
            "variety": "Geisha",
            "process": "Natural",
            "label": "",
            "best_after_days": "10",
            "consume_within_days": "60",
        })
        row = conn.execute("SELECT * FROM coffees WHERE id=?", (coffee_id,)).fetchone()
        assert row["roaster"] == "New Roaster"
        assert row["variety"] == "Geisha"
        assert row["process"] == "Natural"

    def test_edit_coffee_regenerates_label_when_blank(self, client, tmp_db):
        _add_coffee(client, roaster="Alpha", variety="Pacamara", process="Honey", label="Keep Me")
        conn = _get_db(tmp_db)
        coffee_id = conn.execute("SELECT id FROM coffees WHERE roaster='Alpha'").fetchone()["id"]

        client.post(f"/coffee/{coffee_id}/edit", data={
            "roaster": "Beta",
            "variety": "Pacamara",
            "process": "Honey",
            "label": "",  # empty — should auto-generate
        })
        row = conn.execute("SELECT * FROM coffees WHERE id=?", (coffee_id,)).fetchone()
        assert row["label"] == "Beta - Pacamara - Honey"


class TestDeleteCoffee:
    def _seed_full(self, tmp_db):
        conn = _get_db(tmp_db)
        cur = conn.execute("INSERT INTO coffees (label) VALUES (?)", ("Delete Me",))
        coffee_id = cur.lastrowid
        cur2 = conn.execute(
            "INSERT INTO samples (coffee_id, grind_size, grams_in, grams_out, brew_time_sec) VALUES (?,?,?,?,?)",
            (coffee_id, 18, 18, 36, 28),
        )
        sample_id = cur2.lastrowid
        conn.execute(
            "INSERT INTO evaluations (sample_id, aroma, acidity, sweetness, body, balance, overall) VALUES (?,?,?,?,?,?,?)",
            (sample_id, 3, 3, 3, 3, 3, 3),
        )
        conn.commit()
        return coffee_id, sample_id

    def test_delete_coffee_removes_coffee(self, client, tmp_db):
        coffee_id, _ = self._seed_full(tmp_db)
        client.post(f"/coffee/{coffee_id}/delete")
        conn = _get_db(tmp_db)
        row = conn.execute("SELECT * FROM coffees WHERE id=?", (coffee_id,)).fetchone()
        assert row is None

    def test_delete_coffee_cascades_to_samples(self, client, tmp_db):
        coffee_id, _ = self._seed_full(tmp_db)
        client.post(f"/coffee/{coffee_id}/delete")
        conn = _get_db(tmp_db)
        rows = conn.execute("SELECT * FROM samples WHERE coffee_id=?", (coffee_id,)).fetchall()
        assert rows == []

    def test_delete_coffee_cascades_to_evaluations(self, client, tmp_db):
        coffee_id, sample_id = self._seed_full(tmp_db)
        client.post(f"/coffee/{coffee_id}/delete")
        conn = _get_db(tmp_db)
        rows = conn.execute("SELECT * FROM evaluations WHERE sample_id=?", (sample_id,)).fetchall()
        assert rows == []

    def test_delete_coffee_redirects(self, client, tmp_db):
        coffee_id, _ = self._seed_full(tmp_db)
        resp = client.post(f"/coffee/{coffee_id}/delete")
        assert resp.status_code == 302


class TestArchiveCoffee:
    def _insert(self, tmp_db):
        conn = _get_db(tmp_db)
        cur = conn.execute("INSERT INTO coffees (label, archived) VALUES (?,?)", ("Archivable", 0))
        conn.commit()
        return cur.lastrowid

    def test_archive_sets_archived_flag(self, client, tmp_db):
        coffee_id = self._insert(tmp_db)
        client.post(f"/coffee/{coffee_id}/archive")
        conn = _get_db(tmp_db)
        row = conn.execute("SELECT archived FROM coffees WHERE id=?", (coffee_id,)).fetchone()
        assert row["archived"] == 1

    def test_unarchive_clears_archived_flag(self, client, tmp_db):
        conn = _get_db(tmp_db)
        cur = conn.execute("INSERT INTO coffees (label, archived) VALUES (?,?)", ("Already Archived", 1))
        conn.commit()
        coffee_id = cur.lastrowid
        client.post(f"/coffee/{coffee_id}/archive")
        row = conn.execute("SELECT archived FROM coffees WHERE id=?", (coffee_id,)).fetchone()
        assert row["archived"] == 0

    def test_archive_redirects(self, client, tmp_db):
        coffee_id = self._insert(tmp_db)
        resp = client.post(f"/coffee/{coffee_id}/archive")
        assert resp.status_code == 302


class TestCustomTastingNotesCRUD:
    def test_add_custom_note(self, client, tmp_db):
        client.post("/settings/tasting-notes/add", data={"name": "Unicorn Berry", "emoji": "🦄"})
        conn = _get_db(tmp_db)
        row = conn.execute(
            "SELECT * FROM custom_tasting_notes WHERE name='Unicorn Berry'"
        ).fetchone()
        assert row is not None
        assert row["emoji"] == "🦄"

    def test_add_duplicate_note_redirects_with_error(self, client, tmp_db):
        client.post("/settings/tasting-notes/add", data={"name": "Duplicate", "emoji": ""})
        resp = client.post("/settings/tasting-notes/add", data={"name": "Duplicate", "emoji": ""})
        # Should redirect with error=duplicate in query string
        assert resp.status_code == 302
        assert "error=duplicate" in resp.headers["Location"]

    def test_add_duplicate_case_insensitive(self, client, tmp_db):
        client.post("/settings/tasting-notes/add", data={"name": "CaseSensitive", "emoji": ""})
        resp = client.post("/settings/tasting-notes/add", data={"name": "casesensitive", "emoji": ""})
        assert "error=duplicate" in resp.headers["Location"]

    def test_edit_custom_note(self, client, tmp_db):
        client.post("/settings/tasting-notes/add", data={"name": "Edit Me", "emoji": "A"})
        conn = _get_db(tmp_db)
        note_id = conn.execute(
            "SELECT id FROM custom_tasting_notes WHERE name='Edit Me'"
        ).fetchone()["id"]
        client.post(f"/settings/tasting-notes/{note_id}/edit", data={"name": "Edited", "emoji": "B"})
        row = conn.execute("SELECT * FROM custom_tasting_notes WHERE id=?", (note_id,)).fetchone()
        assert row["name"] == "Edited"
        assert row["emoji"] == "B"

    def test_delete_custom_note(self, client, tmp_db):
        client.post("/settings/tasting-notes/add", data={"name": "Delete Me Note", "emoji": ""})
        conn = _get_db(tmp_db)
        note_id = conn.execute(
            "SELECT id FROM custom_tasting_notes WHERE name='Delete Me Note'"
        ).fetchone()["id"]
        client.post(f"/settings/tasting-notes/{note_id}/delete")
        row = conn.execute("SELECT * FROM custom_tasting_notes WHERE id=?", (note_id,)).fetchone()
        assert row is None

    def test_add_note_with_blank_name_does_nothing(self, client, tmp_db):
        client.post("/settings/tasting-notes/add", data={"name": "", "emoji": "X"})
        conn = _get_db(tmp_db)
        count = conn.execute("SELECT COUNT(*) FROM custom_tasting_notes").fetchone()[0]
        assert count == 0


# ===========================================================================
# 2. BUSINESS LOGIC FUNCTIONS
# ===========================================================================

class TestMakeLabel:
    def test_all_three_parts(self):
        assert make_label({"roaster": "Onyx", "variety": "Geisha", "process": "Natural"}) == \
               "Onyx - Geisha - Natural"

    def test_only_roaster(self):
        assert make_label({"roaster": "Onyx", "variety": "", "process": ""}) == "Onyx"

    def test_roaster_and_variety(self):
        assert make_label({"roaster": "Onyx", "variety": "Bourbon", "process": ""}) == \
               "Onyx - Bourbon"

    def test_empty_dict_returns_unnamed(self):
        assert make_label({}) == "Unnamed Coffee"

    def test_all_blank_strings_returns_unnamed(self):
        assert make_label({"roaster": "  ", "variety": "", "process": " "}) == "Unnamed Coffee"

    def test_strips_whitespace_from_parts(self):
        assert make_label({"roaster": " Roaster ", "variety": " V ", "process": " P "}) == \
               "Roaster - V - P"

    def test_missing_keys_ignored(self):
        assert make_label({"roaster": "R"}) == "R"


class TestFreshnessStatus:
    """All freshness stages plus edge cases.

    We fix date.today() via patch to get deterministic results.
    The coffee has best_after_days=7 and consume_within_days=50.
    """

    BASE_COFFEE = {
        "roast_date": "2025-03-01",  # reference: we'll patch today relative to this
        "best_after_days": 7,
        "consume_within_days": 50,
        "bean_color": "Medium",      # Medium: degas=3, peak_dur=11, good_dur=14
    }

    def _status(self, days_since_roast):
        roast_str = "2025-03-01"
        fake_today = date(2025, 3, 1) + timedelta(days=days_since_roast)
        with patch("app.date") as mock_date:
            mock_date.today.return_value = fake_today
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
            return freshness_status(self.BASE_COFFEE)

    def test_no_roast_date_returns_none(self):
        assert freshness_status(_make_coffee_row(roast_date=None)) is None

    def test_invalid_roast_date_returns_none(self):
        assert freshness_status(_make_coffee_row(roast_date="not-a-date")) is None

    def test_future_roast_date_stage(self):
        coffee = _make_coffee_row(roast_date="2025-03-01", best_after_days=7, consume_within_days=50)
        fake_today = date(2025, 2, 28)  # one day before roast
        with patch("app.date") as mock_date:
            mock_date.today.return_value = fake_today
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
            result = freshness_status(coffee)
        assert result["stage"] == "not roasted yet"
        assert result["css"] == "fresh-future"
        assert result["days"] == -1

    def test_degassing_stage(self):
        result = self._status(1)  # day 1 < degas_end (3)
        assert result["stage"] == "degassing"
        assert result["css"] == "fresh-degas"

    def test_degassing_boundary_day_0(self):
        result = self._status(0)  # roast day itself
        assert result["stage"] == "degassing"

    def test_resting_stage(self):
        result = self._status(4)  # day 4: degas_end=3, rest_end=7
        assert result["stage"] == "resting"
        assert result["css"] == "fresh-rest"
        assert "more day" in result["detail"]

    def test_peak_stage_at_rest_end(self):
        result = self._status(7)  # day 7 == rest_end, 7 <= peak_end (7+11=18)
        assert result["stage"] == "peak"
        assert result["css"] == "fresh-peak"

    def test_peak_stage_at_peak_end(self):
        result = self._status(18)  # day 18 == peak_end
        assert result["stage"] == "peak"

    def test_good_stage(self):
        result = self._status(20)  # 18 < 20 <= good_end (7+25=32)
        assert result["stage"] == "good"
        assert result["css"] == "fresh-good"

    def test_fading_stage(self):
        result = self._status(35)  # good_end=32 < 35 <= consume_within=50
        assert result["stage"] == "fading"
        assert result["css"] == "fresh-fading"

    def test_stale_stage(self):
        result = self._status(55)  # 55 > consume_within=50
        assert result["stage"] == "stale"
        assert result["css"] == "fresh-stale"
        assert "Past prime" in result["detail"]

    def test_stale_singular_day_wording(self):
        """'by 1 day' not 'by 1 days'."""
        result = self._status(51)  # over by exactly 1
        assert "1 day" in result["detail"]
        assert "1 days" not in result["detail"]

    def test_resting_singular_day_wording(self):
        """'1 more day' not '1 more days'."""
        result = self._status(6)  # 1 day left to rest_end=7
        assert "1 more day" in result["detail"]
        assert "1 more days" not in result["detail"]

    def test_uses_default_best_after_when_none(self):
        """Without best_after_days, uses roast-level default (Medium-Dark: 5)."""
        coffee = _make_coffee_row(roast_date="2025-03-01", best_after_days=None, consume_within_days=50)
        fake_today = date(2025, 3, 7)  # 6 days after roast, default best_after=5 (Medium-Dark)
        with patch("app.date") as mock_date:
            mock_date.today.return_value = fake_today
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
            result = freshness_status(coffee)
        # day 6 > rest_end(5), <= peak_end(5+9=14) → peak
        assert result["stage"] == "peak"

    def test_days_field_is_correct(self):
        result = self._status(10)
        assert result["days"] == 10

    def test_short_consume_within_no_overlap(self):
        """When consume_within < best_after+25, good_end is clamped — no stage overlap."""
        coffee = _make_coffee_row(roast_date="2025-03-01", best_after_days=7, consume_within_days=30)
        # Day 28: good_end clamped to 30, so 28 <= 30 → still "good" (not stale)
        fake_today = date(2025, 3, 1) + timedelta(days=28)
        with patch("app.date") as mock_date:
            mock_date.today.return_value = fake_today
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
            result = freshness_status(coffee)
        assert result["stage"] == "good"

    def test_short_consume_within_peak_clamped(self):
        """When consume_within < best_after+11, peak stage is clamped."""
        coffee = _make_coffee_row(roast_date="2025-03-01", best_after_days=7, consume_within_days=15)
        # Day 14: consume_within=15 clamps peak_end to 15, so day 14 <= 15 → peak
        fake_today = date(2025, 3, 1) + timedelta(days=14)
        with patch("app.date") as mock_date:
            mock_date.today.return_value = fake_today
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
            result = freshness_status(coffee)
        assert result["stage"] == "peak"

    def test_short_consume_within_stale_after(self):
        """Day beyond consume_within is always stale."""
        coffee = _make_coffee_row(roast_date="2025-03-01", best_after_days=7, consume_within_days=15)
        fake_today = date(2025, 3, 1) + timedelta(days=16)
        with patch("app.date") as mock_date:
            mock_date.today.return_value = fake_today
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
            result = freshness_status(coffee)
        assert result["stage"] == "stale"


class TestFreshnessRoastLevel:
    """Roast-level-dependent freshness windows."""

    def _status_for(self, bean_color, days_since_roast, **kwargs):
        coffee = _make_coffee_row(
            roast_date="2025-03-01", bean_color=bean_color, **kwargs
        )
        fake_today = date(2025, 3, 1) + timedelta(days=days_since_roast)
        with patch("app.date") as mock_date:
            mock_date.today.return_value = fake_today
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
            return freshness_status(coffee)

    def test_light_roast_longer_rest(self):
        """Light roast: best_after=12 by default, so day 10 is still resting."""
        result = self._status_for("Light", 10, best_after_days=None, consume_within_days=None)
        assert result["stage"] == "resting"

    def test_light_roast_peak_at_day_13(self):
        """Light roast: best_after=12, so day 13 is peak."""
        result = self._status_for("Light", 13, best_after_days=None, consume_within_days=None)
        assert result["stage"] == "peak"

    def test_dark_roast_peak_earlier(self):
        """Dark roast: best_after=4, so day 5 is already peak."""
        result = self._status_for("Dark", 5, best_after_days=None, consume_within_days=None)
        assert result["stage"] == "peak"

    def test_dark_roast_stale_earlier(self):
        """Dark roast: consume_within=35, so day 40 is stale."""
        result = self._status_for("Dark", 40, best_after_days=None, consume_within_days=None)
        assert result["stage"] == "stale"

    def test_medium_roast_matches_old_defaults(self):
        """Medium roast windows match the old hardcoded values."""
        result8 = self._status_for("Medium", 8, best_after_days=None, consume_within_days=None)
        result20 = self._status_for("Medium", 20, best_after_days=None, consume_within_days=None)
        assert result8["stage"] == "peak"    # best_after=7, day 8 is peak
        assert result20["stage"] == "good"   # peak_end=18, day 20 is good

    def test_no_bean_color_uses_espresso_default(self):
        """No bean_color → Medium-Dark (espresso roast assumption)."""
        # Medium-Dark: best_after=5, peak_dur=9 → peak_end=14
        result = self._status_for(None, 6, best_after_days=None, consume_within_days=None)
        assert result["stage"] == "peak"

    def test_user_override_takes_precedence(self):
        """Explicit best_after_days overrides roast-level default."""
        # Light default best_after=12, but user sets 3
        result = self._status_for("Light", 4, best_after_days=3)
        assert result["stage"] == "peak"


class TestFreshnessOpenedDate:
    """Opened-date acceleration for freshness."""

    def _status_for(self, days_since_roast, days_open=None, bean_color="Medium"):
        opened = None
        if days_open is not None:
            open_date = date(2025, 3, 1) + timedelta(days=days_since_roast - days_open)
            opened = open_date.strftime("%Y-%m-%d")
        coffee = _make_coffee_row(
            roast_date="2025-03-01", bean_color=bean_color,
            best_after_days=7, consume_within_days=50,
            opened_date=opened,
        )
        fake_today = date(2025, 3, 1) + timedelta(days=days_since_roast)
        with patch("app.date") as mock_date:
            mock_date.today.return_value = fake_today
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
            return freshness_status(coffee)

    def test_no_opened_date_no_penalty(self):
        """Without opened_date, no acceleration."""
        result = self._status_for(10)  # day 10, peak (7+11=18)
        assert result["stage"] == "peak"

    def test_recently_opened_no_penalty(self):
        """Opened 5 days ago (<=7) — no penalty."""
        result = self._status_for(10, days_open=5)
        assert result["stage"] == "peak"

    def test_opened_8_days_adds_penalty(self):
        """Opened 8 days (>7) — +5 day penalty, may shift stage."""
        # day 15, effective=20, peak_end=18 → good
        result = self._status_for(15, days_open=8)
        assert result["stage"] == "good"
        assert "open" in result["detail"]

    def test_opened_15_days_larger_penalty(self):
        """Opened 15 days (>14) — +12 day penalty."""
        # day 20, effective=32, good_end=7+11+14=32 → good (boundary)
        result = self._status_for(20, days_open=15)
        assert result["stage"] == "good"

    def test_opened_22_days_max_penalty(self):
        """Opened 22 days (>21) — +20 day penalty."""
        # day 15, effective=35, good_end=32 → fading
        result = self._status_for(15, days_open=22)
        assert result["stage"] == "fading"
        assert "open" in result["detail"]

    def test_days_field_still_real_days(self):
        """The days field should reflect actual days since roast, not effective."""
        result = self._status_for(15, days_open=22)
        assert result["days"] == 15  # real days, not effective


class TestDiagnose:
    def test_under_extracted_full_pattern(self):
        tips = diagnose({"acidity": 5, "sweetness": 1, "body": 1, "balance": 3, "overall": 3})
        assert any("under-extracted" in t for t in tips)

    def test_high_acidity_low_sweetness(self):
        tips = diagnose({"acidity": 4, "sweetness": 2, "body": 3, "balance": 3, "overall": 3})
        assert any("under-extracted" in t.lower() for t in tips)

    def test_over_extracted_pattern(self):
        tips = diagnose({"acidity": 1, "sweetness": 2, "body": 3, "balance": 3, "overall": 3})
        assert any("over-extracted" in t for t in tips)

    def test_thin_body_sweet(self):
        tips = diagnose({"acidity": 3, "sweetness": 4, "body": 1, "balance": 3, "overall": 3})
        assert any("body" in t.lower() for t in tips)

    def test_great_shot(self):
        tips = diagnose({"acidity": 3, "sweetness": 3, "body": 3, "balance": 4, "overall": 4})
        assert any("Great shot" in t for t in tips)

    def test_solid_shot_no_specific_issue(self):
        # No specific issue, overall >= 4
        tips = diagnose({"acidity": 3, "sweetness": 3, "body": 3, "balance": 3, "overall": 4})
        assert any("Solid shot" in t for t in tips)

    def test_balanced_mediocre_has_no_tips(self):
        # No issue found, overall < 4 — should return empty list
        tips = diagnose({"acidity": 3, "sweetness": 3, "body": 3, "balance": 3, "overall": 3})
        assert tips == []

    def test_defaults_used_when_keys_missing(self):
        # Should not raise; missing keys default to 3
        tips = diagnose({})
        assert isinstance(tips, list)

    def test_over_extracted_boundary(self):
        tips = diagnose({"acidity": 2, "sweetness": 2, "body": 3, "balance": 3, "overall": 3})
        assert any("over-extracted" in t for t in tips)

    def test_none_scores_do_not_crash(self):
        """Submitting eval without selecting any radio buttons should not raise."""
        tips = diagnose({"acidity": None, "sweetness": None, "body": None,
                         "balance": None, "overall": None})
        assert isinstance(tips, list)

    def test_partial_none_scores(self):
        """Mix of None and real scores should not raise."""
        tips = diagnose({"acidity": 5, "sweetness": None, "body": None,
                         "balance": 3, "overall": 4})
        assert isinstance(tips, list)


class _GrindTestBase:
    """Shared helpers for grind algorithm test classes."""

    def _make_conn(self, tmp_db):
        conn = sqlite3.connect(tmp_db)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _seed_coffee(self, conn):
        cur = conn.execute("INSERT INTO coffees (label) VALUES (?)", ("Grind Test",))
        conn.commit()
        return cur.lastrowid

    def _seed_shot(self, conn, coffee_id, grind, overall):
        cur = conn.execute(
            "INSERT INTO samples (coffee_id, grind_size, grams_in, grams_out, brew_time_sec) VALUES (?,?,?,?,?)",
            (coffee_id, grind, 18, 36, 28),
        )
        sample_id = cur.lastrowid
        conn.execute(
            "INSERT INTO evaluations (sample_id, aroma, acidity, sweetness, body, balance, overall) VALUES (?,?,?,?,?,?,?)",
            (sample_id, 3, 3, 3, 3, 3, overall),
        )
        conn.commit()
        return sample_id


class TestSuggestGrind(_GrindTestBase):
    """Tests for the quadratic regression algorithm (original)."""

    def _set_quadratic(self, conn):
        set_setting(conn, "grind_algorithm", "quadratic")

    def test_no_data_returns_none(self, tmp_db):
        conn = self._make_conn(tmp_db)
        self._set_quadratic(conn)
        coffee_id = self._seed_coffee(conn)
        result = suggest_grind(coffee_id, conn)
        assert result is None

    def test_one_shot_returns_low_confidence(self, tmp_db):
        conn = self._make_conn(tmp_db)
        self._set_quadratic(conn)
        coffee_id = self._seed_coffee(conn)
        self._seed_shot(conn, coffee_id, 18.0, 4)
        result = suggest_grind(coffee_id, conn)
        assert result is not None
        assert result["confidence"] == "low"
        assert result["grind"] == 18.0

    def test_two_shots_returns_best_grind_low_confidence(self, tmp_db):
        conn = self._make_conn(tmp_db)
        self._set_quadratic(conn)
        coffee_id = self._seed_coffee(conn)
        self._seed_shot(conn, coffee_id, 17.0, 3)
        self._seed_shot(conn, coffee_id, 19.0, 5)
        result = suggest_grind(coffee_id, conn)
        assert result["confidence"] == "low"
        assert result["grind"] == 19.0  # best shot

    def test_three_plus_shots_returns_result(self, tmp_db):
        conn = self._make_conn(tmp_db)
        self._set_quadratic(conn)
        coffee_id = self._seed_coffee(conn)
        self._seed_shot(conn, coffee_id, 18.0, 3)
        self._seed_shot(conn, coffee_id, 20.0, 5)
        self._seed_shot(conn, coffee_id, 22.0, 3)
        result = suggest_grind(coffee_id, conn)
        assert result is not None
        assert "grind" in result
        assert "confidence" in result

    def test_six_plus_shots_medium_or_high_confidence(self, tmp_db):
        conn = self._make_conn(tmp_db)
        self._set_quadratic(conn)
        coffee_id = self._seed_coffee(conn)
        grinds = [16.0, 17.0, 18.0, 19.0, 20.0, 21.0, 22.0]
        scores = [2,     3,    4,    5,    4,    3,    2]
        for g, s in zip(grinds, scores):
            self._seed_shot(conn, coffee_id, g, s)
        result = suggest_grind(coffee_id, conn)
        assert result is not None
        assert result["confidence"] in ("medium", "high")

    def test_detail_contains_shot_count(self, tmp_db):
        conn = self._make_conn(tmp_db)
        self._set_quadratic(conn)
        coffee_id = self._seed_coffee(conn)
        self._seed_shot(conn, coffee_id, 18.0, 3)
        result = suggest_grind(coffee_id, conn)
        assert "1 shot" in result["detail"]

    def test_detail_plural_shots(self, tmp_db):
        conn = self._make_conn(tmp_db)
        self._set_quadratic(conn)
        coffee_id = self._seed_coffee(conn)
        self._seed_shot(conn, coffee_id, 17.0, 3)
        self._seed_shot(conn, coffee_id, 19.0, 4)
        result = suggest_grind(coffee_id, conn)
        assert "2 shots" in result["detail"]


class TestSuggestGrindCentroid(_GrindTestBase):
    """Tests for the weighted centroid algorithm (Gemini)."""

    def test_no_data_returns_none(self, tmp_db):
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed_coffee(conn)
        result = _suggest_grind_centroid(coffee_id, conn)
        assert result is None

    def test_one_shot_returns_low_fallback(self, tmp_db):
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed_coffee(conn)
        self._seed_shot(conn, coffee_id, 15.0, 4)
        result = _suggest_grind_centroid(coffee_id, conn)
        assert result is not None
        assert result["confidence"] == "low"
        assert result["grind"] == 15.0

    def test_two_shots_weighted_toward_better(self, tmp_db):
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed_coffee(conn)
        self._seed_shot(conn, coffee_id, 14.0, 2)
        self._seed_shot(conn, coffee_id, 20.0, 5)
        result = _suggest_grind_centroid(coffee_id, conn)
        # With score^2 weighting, the 5-score shot should dominate
        assert result["grind"] > 17.0

    def test_many_shots_high_confidence(self, tmp_db):
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed_coffee(conn)
        for g, s in [(16, 3), (17, 4), (18, 5), (19, 4), (20, 3), (21, 2)]:
            self._seed_shot(conn, coffee_id, float(g), s)
        result = _suggest_grind_centroid(coffee_id, conn)
        assert result["confidence"] == "high"
        # Should be near 18 (the best-scoring grind)
        assert 16.5 < result["grind"] < 19.5

    def test_custom_params_applied(self, tmp_db):
        conn = self._make_conn(tmp_db)
        import json
        set_setting(conn, "grind_centroid_params", json.dumps({"top_n": 1, "decay_rate": 0, "score_weight_power": 1}))
        coffee_id = self._seed_coffee(conn)
        self._seed_shot(conn, coffee_id, 10.0, 3)
        self._seed_shot(conn, coffee_id, 20.0, 5)
        result = _suggest_grind_centroid(coffee_id, conn)
        # top_n=1 with no decay → picks the single best shot's grind
        assert result["grind"] == 20.0

    def test_default_is_centroid(self, tmp_db):
        """Default algorithm should be weighted_centroid."""
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed_coffee(conn)
        self._seed_shot(conn, coffee_id, 18.0, 4)
        self._seed_shot(conn, coffee_id, 20.0, 5)
        # No setting written → defaults to centroid
        result = suggest_grind(coffee_id, conn)
        assert result is not None


class TestSuggestGrindBayesian(_GrindTestBase):
    """Tests for the Bayesian quadratic algorithm (Perplexity)."""

    def test_no_data_returns_none(self, tmp_db):
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed_coffee(conn)
        result = _suggest_grind_bayesian(coffee_id, conn)
        assert result is None

    def test_two_shots_low_fallback(self, tmp_db):
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed_coffee(conn)
        self._seed_shot(conn, coffee_id, 15.0, 3)
        self._seed_shot(conn, coffee_id, 20.0, 5)
        result = _suggest_grind_bayesian(coffee_id, conn)
        assert result["confidence"] == "low"

    def test_parabola_finds_peak(self, tmp_db):
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed_coffee(conn)
        # Clear parabola: peak at 19
        for g, s in [(16, 2), (17, 3), (18, 4), (19, 5), (20, 4), (21, 3), (22, 2)]:
            self._seed_shot(conn, coffee_id, float(g), s)
        result = _suggest_grind_bayesian(coffee_id, conn)
        assert result is not None
        assert result["confidence"] == "high"
        # Regularization may shift slightly from 19, but should be close
        assert 17.5 < result["grind"] < 20.5

    def test_regularization_prevents_wild_extrapolation(self, tmp_db):
        """With high prior_strength, the model should be conservative."""
        conn = self._make_conn(tmp_db)
        import json
        set_setting(conn, "grind_bayesian_params", json.dumps({"prior_strength": 10.0, "decay_rate": 0, "use_recency": False}))
        coffee_id = self._seed_coffee(conn)
        # Noisy data with slight trend
        self._seed_shot(conn, coffee_id, 10.0, 3)
        self._seed_shot(conn, coffee_id, 20.0, 4)
        self._seed_shot(conn, coffee_id, 30.0, 3)
        result = _suggest_grind_bayesian(coffee_id, conn)
        assert result is not None
        # Strong regularization → grind should be within observed range
        assert 10.0 <= result["grind"] <= 30.0

    def test_dispatch_bayesian(self, tmp_db):
        """Algorithm dispatch to bayesian works."""
        conn = self._make_conn(tmp_db)
        set_setting(conn, "grind_algorithm", "bayesian_quadratic")
        coffee_id = self._seed_coffee(conn)
        for g, s in [(18, 3), (20, 5), (22, 3)]:
            self._seed_shot(conn, coffee_id, float(g), s)
        result = suggest_grind(coffee_id, conn)
        assert result is not None
        assert "Cautious curve" in result["detail"]


class TestAppSettings:
    """Tests for the app_settings table and helpers."""

    def _make_conn(self, tmp_db):
        conn = sqlite3.connect(tmp_db)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def test_get_setting_default(self, tmp_db):
        conn = self._make_conn(tmp_db)
        assert get_setting(conn, "nonexistent", "fallback") == "fallback"

    def test_get_setting_none_default(self, tmp_db):
        conn = self._make_conn(tmp_db)
        assert get_setting(conn, "nonexistent") is None

    def test_set_and_get(self, tmp_db):
        conn = self._make_conn(tmp_db)
        set_setting(conn, "test_key", "test_val")
        assert get_setting(conn, "test_key") == "test_val"

    def test_upsert(self, tmp_db):
        conn = self._make_conn(tmp_db)
        set_setting(conn, "k", "v1")
        set_setting(conn, "k", "v2")
        assert get_setting(conn, "k") == "v2"


class TestSettingsGrindRoutes:
    """Tests for the /settings/grind routes."""

    def test_get_settings_grind(self, client):
        resp = client.get("/settings/grind")
        assert resp.status_code == 200
        assert b"Grind Optimizer" in resp.data

    def test_save_settings_grind(self, client, tmp_db):
        resp = client.post("/settings/grind/save", data={
            "algorithm": "bayesian_quadratic",
            "centroid_decay_rate": "0.1",
            "centroid_top_n": "5",
            "centroid_score_power": "3",
            "bayesian_prior_strength": "2.0",
            "bayesian_decay_rate": "0.08",
            "bayesian_use_recency": "1",
        })
        assert resp.status_code == 302  # redirect

        conn = sqlite3.connect(tmp_db)
        conn.row_factory = sqlite3.Row
        assert get_setting(conn, "grind_algorithm") == "bayesian_quadratic"

    def test_save_invalid_algo_defaults_centroid(self, client, tmp_db):
        resp = client.post("/settings/grind/save", data={"algorithm": "invalid"})
        assert resp.status_code == 302
        conn = sqlite3.connect(tmp_db)
        conn.row_factory = sqlite3.Row
        assert get_setting(conn, "grind_algorithm") == "weighted_centroid"

    def test_auto_save_returns_json(self, client):
        resp = client.post("/settings/grind/save",
                           data={"algorithm": "quadratic"},
                           headers={"X-Auto-Save": "1"})
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True


# ===========================================================================
# NEW TESTS — appended after TestSettingsGrindRoutes
# ===========================================================================


class TestExtractScore:
    """Tests for _extract_score — the per-row score extraction helper."""

    def _row(self, **kwargs):
        """Return a dict that quacks like a sqlite3.Row for _extract_score."""
        defaults = {
            "overall": None,
            "aroma": None,
            "acidity": None,
            "sweetness": None,
            "body": None,
            "balance": None,
            "grams_out": None,
        }
        defaults.update(kwargs)
        return defaults

    def test_overall_default(self):
        row = self._row(overall=4)
        assert _extract_score(row, "overall") == 4

    def test_taste_avg(self):
        row = self._row(aroma=3, acidity=5, sweetness=4, body=2, balance=4)
        result = _extract_score(row, "taste_avg")
        assert result == 3.6

    def test_taste_avg_with_none_dims(self):
        # Only aroma=3 and acidity=5 are valid; others are None
        row = self._row(aroma=3, acidity=5, sweetness=None, body=None, balance=None)
        result = _extract_score(row, "taste_avg")
        assert result == 4.0

    def test_ratio_accuracy_within_1g(self):
        row = self._row(grams_out=36)
        assert _extract_score(row, "ratio_accuracy", target_out=36) == 5.0

    def test_ratio_accuracy_within_2g(self):
        row = self._row(grams_out=38)
        assert _extract_score(row, "ratio_accuracy", target_out=36) == 4.0

    def test_ratio_accuracy_within_4g(self):
        row = self._row(grams_out=40)
        assert _extract_score(row, "ratio_accuracy", target_out=36) == 3.0

    def test_ratio_accuracy_within_7g(self):
        row = self._row(grams_out=43)
        assert _extract_score(row, "ratio_accuracy", target_out=36) == 2.0

    def test_ratio_accuracy_beyond_7g(self):
        row = self._row(grams_out=50)
        assert _extract_score(row, "ratio_accuracy", target_out=36) == 1.0

    def test_ratio_accuracy_no_target(self):
        row = self._row(grams_out=36)
        assert _extract_score(row, "ratio_accuracy", target_out=None) is None

    def test_single_dimension_sweetness(self):
        row = self._row(sweetness=5)
        assert _extract_score(row, "sweetness") == 5

    def test_single_dimension_acidity(self):
        row = self._row(acidity=2)
        assert _extract_score(row, "acidity") == 2

    def test_single_dimension_body(self):
        row = self._row(body=3)
        assert _extract_score(row, "body") == 3

    def test_single_dimension_balance(self):
        row = self._row(balance=4)
        assert _extract_score(row, "balance") == 4

    def test_single_dimension_aroma(self):
        row = self._row(aroma=1)
        assert _extract_score(row, "aroma") == 1

    def test_taste_avg_all_none_returns_none(self):
        row = self._row()
        assert _extract_score(row, "taste_avg") is None

    def test_ratio_accuracy_exact_boundary_1g(self):
        # dev == 1 is still within_1 → 5.0
        row = self._row(grams_out=37)
        assert _extract_score(row, "ratio_accuracy", target_out=36) == 5.0

    def test_ratio_accuracy_exact_boundary_2g(self):
        # dev == 2 → 4.0
        row = self._row(grams_out=34)
        assert _extract_score(row, "ratio_accuracy", target_out=36) == 4.0


class TestGrindRowsFiltering(_GrindTestBase):
    """Tests for _grind_rows recipe-matching filter logic."""

    def _seed_shot_with_params(self, conn, coffee_id, grind, overall, temp=None, dose=18.0):
        """Insert a sample+evaluation with custom temp/dose."""
        cur = conn.execute(
            "INSERT INTO samples (coffee_id, grind_size, grams_in, grams_out, brew_time_sec, brew_temp_c) VALUES (?,?,?,?,?,?)",
            (coffee_id, grind, dose, 36, 28, temp),
        )
        sample_id = cur.lastrowid
        conn.execute(
            "INSERT INTO evaluations (sample_id, aroma, acidity, sweetness, body, balance, overall) VALUES (?,?,?,?,?,?,?)",
            (sample_id, 3, 3, 3, 3, 3, overall),
        )
        conn.commit()
        return sample_id

    def _set_match_recipe(self, conn, temp_tolerance=2.0, dose_tolerance=1.0):
        import json
        set_setting(conn, "grind_filter_params", json.dumps({
            "score_source": "overall",
            "match_recipe": True,
            "temp_tolerance": temp_tolerance,
            "dose_tolerance": dose_tolerance,
        }))

    def test_match_recipe_filters_by_temp(self, tmp_db):
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed_coffee(conn)
        # Two shots at 91°C, one at 95°C (outside tolerance=2 from latest at 91°C)
        self._seed_shot_with_params(conn, coffee_id, grind=18.0, overall=3, temp=95.0)
        self._seed_shot_with_params(conn, coffee_id, grind=19.0, overall=4, temp=91.0)
        self._seed_shot_with_params(conn, coffee_id, grind=20.0, overall=5, temp=91.0)  # latest
        self._set_match_recipe(conn, temp_tolerance=2.0)
        rows = _grind_rows(coffee_id, conn)
        # Only the two 91°C shots should survive
        assert len(rows) == 2
        temps = {r.get("brew_temp_c") for r in rows}
        assert temps == {91.0}

    def test_match_recipe_filters_by_dose(self, tmp_db):
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed_coffee(conn)
        # Two shots at 18g dose, one at 22g (outside tolerance=1 from latest at 18g)
        self._seed_shot_with_params(conn, coffee_id, grind=18.0, overall=3, dose=22.0)
        self._seed_shot_with_params(conn, coffee_id, grind=19.0, overall=4, dose=18.0)
        self._seed_shot_with_params(conn, coffee_id, grind=20.0, overall=5, dose=18.0)  # latest
        self._set_match_recipe(conn, dose_tolerance=1.0)
        rows = _grind_rows(coffee_id, conn)
        # Only the two 18g shots should survive
        assert len(rows) == 2
        doses = {r["grams_in"] for r in rows}
        assert doses == {18.0}

    def test_match_recipe_off_includes_all(self, tmp_db):
        conn = self._make_conn(tmp_db)
        import json
        set_setting(conn, "grind_filter_params", json.dumps({
            "score_source": "overall",
            "match_recipe": False,
            "temp_tolerance": 2.0,
            "dose_tolerance": 1.0,
        }))
        coffee_id = self._seed_coffee(conn)
        self._seed_shot_with_params(conn, coffee_id, grind=18.0, overall=3, temp=88.0)
        self._seed_shot_with_params(conn, coffee_id, grind=19.0, overall=4, temp=91.0)
        self._seed_shot_with_params(conn, coffee_id, grind=20.0, overall=5, temp=95.0)
        rows = _grind_rows(coffee_id, conn)
        assert len(rows) == 3

    def test_no_shots_returns_empty(self, tmp_db):
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed_coffee(conn)
        rows = _grind_rows(coffee_id, conn)
        assert rows == []


class TestCrossCoffeePrior(_GrindTestBase):
    """Tests for _cross_coffee_prior — grind starting-point from other coffees."""

    def _seed_coffee_full(self, conn, label, process=None, bean_color=None):
        """Insert a coffee with process and bean_color set."""
        cur = conn.execute(
            "INSERT INTO coffees (label, process, bean_color) VALUES (?,?,?)",
            (label, process, bean_color),
        )
        conn.commit()
        return cur.lastrowid

    def _seed_three_shots(self, conn, coffee_id, grind=18.0):
        """Seed 3 shots to meet the prior's minimum shot count."""
        for i in range(3):
            self._seed_shot(conn, coffee_id, grind + i * 0.5, 4)

    def test_no_other_coffees_returns_none(self, tmp_db):
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed_coffee_full(conn, "Solo Coffee", process="Washed", bean_color="Medium")
        # Give this coffee shots (prior excludes the target coffee itself)
        self._seed_three_shots(conn, coffee_id)
        result = _cross_coffee_prior(coffee_id, conn)
        assert result is None

    def test_same_process_and_color(self, tmp_db):
        conn = self._make_conn(tmp_db)
        # Target coffee — no shots yet
        target_id = self._seed_coffee_full(conn, "Target", process="Natural", bean_color="Medium")
        # Other coffee — same process + bean_color, 3 shots at grind ~20
        other_id = self._seed_coffee_full(conn, "Other", process="Natural", bean_color="Medium")
        self._seed_three_shots(conn, other_id, grind=20.0)
        result = _cross_coffee_prior(target_id, conn)
        assert result is not None
        assert "Natural" in result["match"]
        assert "Medium" in result["match"]
        assert abs(result["grind"] - 20.25) < 0.5

    def test_fallback_to_process_only(self, tmp_db):
        conn = self._make_conn(tmp_db)
        target_id = self._seed_coffee_full(conn, "Target", process="Washed", bean_color="Dark")
        # Other coffee — same process, different bean_color
        other_id = self._seed_coffee_full(conn, "Other", process="Washed", bean_color="Light")
        self._seed_three_shots(conn, other_id, grind=17.0)
        result = _cross_coffee_prior(target_id, conn)
        assert result is not None
        assert "Washed" in result["match"]

    def test_fallback_to_all(self, tmp_db):
        conn = self._make_conn(tmp_db)
        target_id = self._seed_coffee_full(conn, "Target", process="Natural", bean_color="Dark")
        # Other coffee — different process and bean_color
        other_id = self._seed_coffee_full(conn, "Other", process="Washed", bean_color="Light")
        self._seed_three_shots(conn, other_id, grind=19.0)
        result = _cross_coffee_prior(target_id, conn)
        assert result is not None
        assert result["match"] == "all your coffees"

    def test_missing_process_and_color_fallback_to_all(self, tmp_db):
        conn = self._make_conn(tmp_db)
        target_id = self._seed_coffee_full(conn, "Target", process=None, bean_color=None)
        other_id = self._seed_coffee_full(conn, "Other", process="Washed", bean_color="Medium")
        self._seed_three_shots(conn, other_id, grind=18.0)
        result = _cross_coffee_prior(target_id, conn)
        assert result is not None
        assert result["match"] == "all your coffees"

    def test_other_coffee_below_min_shots_skipped(self, tmp_db):
        conn = self._make_conn(tmp_db)
        target_id = self._seed_coffee_full(conn, "Target", process="Natural", bean_color="Medium")
        # Other coffee with same attrs but only 2 shots (below threshold of 3)
        other_id = self._seed_coffee_full(conn, "Other", process="Natural", bean_color="Medium")
        self._seed_shot(conn, other_id, 18.0, 4)
        self._seed_shot(conn, other_id, 19.0, 5)
        result = _cross_coffee_prior(target_id, conn)
        assert result is None


class TestPreviewAPI:
    """Tests for the /api/grind-preview endpoint."""

    def _make_shots(self, n=6):
        """Generate n sample shots with a clear parabolic peak at grind 20."""
        grind_values = [16, 17, 18, 19, 20, 21, 22]
        score_values = [2, 3, 4, 5, 4, 3, 2]
        shots = []
        for i in range(n):
            idx = i % len(grind_values)
            shots.append({
                "grind": grind_values[idx],
                "score": score_values[idx],
                "dose": 18,
                "output": 36,
                "time": 28,
                "temp": 91,
                "daysAgo": i,
            })
        return shots

    def test_basic_preview(self, client):
        payload = {
            "shots": self._make_shots(6),
            "algorithm": "weighted_centroid",
        }
        resp = client.post("/api/grind-preview", json=payload)
        assert resp.status_code == 200
        data = resp.get_json()
        assert "grind" in data
        assert "confidence" in data
        assert "detail" in data

    def test_preview_low_data(self, client):
        payload = {
            "shots": [{"grind": 18, "score": 4, "dose": 18, "output": 36, "time": 28, "temp": 91, "daysAgo": 0}],
            "algorithm": "weighted_centroid",
        }
        resp = client.post("/api/grind-preview", json=payload)
        assert resp.status_code == 200
        data = resp.get_json()
        # Even low-data should return a result (grind key present, confidence low or None handled)
        assert "grind" in data

    def test_preview_empty_shots(self, client):
        payload = {"shots": [], "algorithm": "weighted_centroid"}
        resp = client.post("/api/grind-preview", json=payload)
        assert resp.status_code == 200
        data = resp.get_json()
        assert "error" in data

    def test_preview_ratio_accuracy(self, client):
        shots = self._make_shots(6)
        payload = {
            "shots": shots,
            "algorithm": "weighted_centroid",
            "filter_params": {"score_source": "ratio_accuracy"},
            "target_output": 36,
        }
        resp = client.post("/api/grind-preview", json=payload)
        assert resp.status_code == 200
        data = resp.get_json()
        assert "grind" in data

    def test_preview_all_algorithms(self, client):
        shots = self._make_shots(7)
        for algo in ("weighted_centroid", "quadratic", "bayesian_quadratic"):
            payload = {"shots": shots, "algorithm": algo}
            resp = client.post("/api/grind-preview", json=payload)
            assert resp.status_code == 200
            data = resp.get_json()
            assert "grind" in data, f"algorithm {algo!r} did not return grind key"

    def test_preview_no_body_returns_error(self, client):
        # Posting no JSON body — shots defaults to [] → error
        resp = client.post("/api/grind-preview", data="", content_type="application/json")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "error" in data


class TestSameGrindDegenerate(_GrindTestBase):
    """Edge cases: all shots at identical grind settings (singular / degenerate input)."""

    def test_all_same_grind_quadratic(self, tmp_db):
        conn = self._make_conn(tmp_db)
        set_setting(conn, "grind_algorithm", "quadratic")
        coffee_id = self._seed_coffee(conn)
        for score in [2, 3, 4, 5, 3]:
            self._seed_shot(conn, coffee_id, 18.0, score)
        # Must not raise; singular matrix handled gracefully
        result = suggest_grind(coffee_id, conn)
        assert result is not None
        assert "grind" in result

    def test_all_same_grind_bayesian(self, tmp_db):
        conn = self._make_conn(tmp_db)
        set_setting(conn, "grind_algorithm", "bayesian_quadratic")
        coffee_id = self._seed_coffee(conn)
        for score in [2, 3, 4, 5, 3]:
            self._seed_shot(conn, coffee_id, 18.0, score)
        result = suggest_grind(coffee_id, conn)
        assert result is not None
        assert "grind" in result

    def test_all_same_grind_centroid(self, tmp_db):
        conn = self._make_conn(tmp_db)
        set_setting(conn, "grind_algorithm", "weighted_centroid")
        coffee_id = self._seed_coffee(conn)
        for score in [3, 4, 5, 4, 3]:
            self._seed_shot(conn, coffee_id, 20.0, score)
        result = suggest_grind(coffee_id, conn)
        assert result is not None
        assert result["grind"] == 20.0


class TestSuggestGrindRatio(_GrindTestBase):
    """Tests for the ratio-accuracy directed grind search algorithm."""

    import json as _json

    def _seed_coffee_with_target(self, conn, target_out):
        cur = conn.execute(
            "INSERT INTO coffees (label, default_grams_out) VALUES (?, ?)",
            ("Ratio Test", target_out),
        )
        conn.commit()
        return cur.lastrowid

    def _seed_ratio_shot(self, conn, coffee_id, grind, grams_out, grams_in=18):
        cur = conn.execute(
            "INSERT INTO samples (coffee_id, grind_size, grams_in, grams_out, brew_time_sec) VALUES (?,?,?,?,?)",
            (coffee_id, grind, grams_in, grams_out, 28),
        )
        sample_id = cur.lastrowid
        conn.execute(
            "INSERT INTO evaluations (sample_id, overall) VALUES (?,?)",
            (sample_id, 3),
        )
        conn.commit()
        return sample_id

    def test_no_target_output(self, tmp_db):
        """Coffee with no default_grams_out → returns detail about setting target."""
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed_coffee(conn)  # no target set
        result = _suggest_grind_ratio(coffee_id, conn)
        assert result is not None
        assert result["grind"] is None
        assert "target" in result["detail"].lower()

    def test_no_shots(self, tmp_db):
        """Coffee with target but no shots with grams_out → returns None (no cross-coffee data)."""
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed_coffee_with_target(conn, 36)
        result = _suggest_grind_ratio(coffee_id, conn)
        assert result is None

    def test_on_target(self, tmp_db):
        """Latest shot output within 1g of target → On target! message."""
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed_coffee_with_target(conn, 36)
        self._seed_ratio_shot(conn, coffee_id, 18.0, 36)
        result = _suggest_grind_ratio(coffee_id, conn)
        assert result is not None
        assert "On target" in result["detail"]
        assert result["confidence"] == "high"

    def test_output_too_high_suggests_finer(self, tmp_db):
        """Output 42g vs target 36g → suggested grind is lower than latest (finer)."""
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed_coffee_with_target(conn, 36)
        self._seed_ratio_shot(conn, coffee_id, 18.0, 42)
        result = _suggest_grind_ratio(coffee_id, conn)
        assert result is not None
        assert result["grind"] < 18.0  # finer = lower grind number

    def test_output_too_low_suggests_coarser(self, tmp_db):
        """Output 30g vs target 36g → suggested grind is higher than latest (coarser)."""
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed_coffee_with_target(conn, 36)
        self._seed_ratio_shot(conn, coffee_id, 18.0, 30)
        result = _suggest_grind_ratio(coffee_id, conn)
        assert result is not None
        assert result["grind"] > 18.0  # coarser = higher grind number

    def test_sensitivity_from_history(self, tmp_db):
        """3 shots at different grinds with clear output trend → uses learned sensitivity."""
        import json
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed_coffee_with_target(conn, 36)
        # Clear trend: each grind step changes output by 4g (steeper than default 2.0)
        self._seed_ratio_shot(conn, coffee_id, 16.0, 28)
        self._seed_ratio_shot(conn, coffee_id, 18.0, 36)
        self._seed_ratio_shot(conn, coffee_id, 20.0, 44)
        # Latest shot: grind=20, output=44 → 8g over target → need ~2 steps finer
        result = _suggest_grind_ratio(coffee_id, conn)
        assert result is not None
        # With learned sensitivity ~4 g/step, adjustment = 8/4 = 2 steps → suggested ~18
        # With default sensitivity 2.0, adjustment = 8/2 = 4 steps → suggested ~16
        # Learned sensitivity should give a suggestion closer to 18 than 16
        assert result["grind"] > 16.0

    def test_single_shot_uses_default_sensitivity(self, tmp_db):
        """1 shot → uses DEFAULT_GRIND_SENSITIVITY (2.0)."""
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed_coffee_with_target(conn, 36)
        self._seed_ratio_shot(conn, coffee_id, 18.0, 40)  # 4g over target
        result = _suggest_grind_ratio(coffee_id, conn)
        assert result is not None
        # With default sensitivity 2.0: steps = 4/2 = 2, suggested = 18 - 2 = 16
        assert result["grind"] == 16.0

    def test_reversed_grinder(self, tmp_db):
        """finer_is_lower=False → output too high means suggest higher grind number."""
        import json
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed_coffee_with_target(conn, 36)
        self._seed_ratio_shot(conn, coffee_id, 18.0, 42)  # 6g over target
        set_setting(conn, "grind_filter_params", json.dumps({
            "score_source": "ratio_accuracy",
            "finer_is_lower": False,
            "match_recipe": False,
            "temp_tolerance": 2.0,
            "dose_tolerance": 1.0,
        }))
        result = _suggest_grind_ratio(coffee_id, conn)
        assert result is not None
        # Reversed: output too high → grind number should increase (not decrease)
        assert result["grind"] > 18.0

    def test_same_grind_all_shots(self, tmp_db):
        """All shots at same grind → sensitivity fallback to default, no crash."""
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed_coffee_with_target(conn, 36)
        for out in [34, 35, 37, 38]:
            self._seed_ratio_shot(conn, coffee_id, 18.0, out)
        result = _suggest_grind_ratio(coffee_id, conn)
        assert result is not None
        assert "grind" in result
        assert result["grind"] is not None


class TestCoffeeRating:
    def _make_conn(self, tmp_db):
        conn = sqlite3.connect(tmp_db)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _seed(self, conn, representative=True, scores=None):
        scores = scores or {"aroma": 4, "acidity": 4, "sweetness": 4, "body": 4, "balance": 4, "overall": 4}
        cur = conn.execute("INSERT INTO coffees (label) VALUES (?)", ("Rating Coffee",))
        coffee_id = cur.lastrowid
        cur2 = conn.execute(
            "INSERT INTO samples (coffee_id, grind_size, grams_in, grams_out, brew_time_sec) VALUES (?,?,?,?,?)",
            (coffee_id, 18, 18, 36, 28),
        )
        sample_id = cur2.lastrowid
        conn.execute(
            "INSERT INTO evaluations (sample_id, aroma, acidity, sweetness, body, balance, overall, representative) VALUES (?,?,?,?,?,?,?,?)",
            (sample_id, scores["aroma"], scores["acidity"], scores["sweetness"],
             scores["body"], scores["balance"], scores["overall"], 1 if representative else 0),
        )
        conn.commit()
        return coffee_id

    def test_no_representative_shots_returns_none(self, tmp_db):
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed(conn, representative=False)
        result = coffee_rating(coffee_id, conn)
        assert result is None

    def test_returns_dict_with_required_keys(self, tmp_db):
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed(conn)
        result = coffee_rating(coffee_id, conn)
        assert result is not None
        for key in ("tier", "css", "quality", "avg_overall", "profile", "avgs", "n"):
            assert key in result

    def test_outstanding_tier(self, tmp_db):
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed(conn, scores={
            "aroma": 5, "acidity": 5, "sweetness": 5, "body": 5, "balance": 5, "overall": 5
        })
        result = coffee_rating(coffee_id, conn)
        assert result["tier"] == "Outstanding"
        assert result["css"] == "tier-outstanding"

    def test_excellent_tier(self, tmp_db):
        # quality = (sweetness + balance + 2*overall) / 4
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed(conn, scores={
            "aroma": 3, "acidity": 3, "sweetness": 4, "body": 3, "balance": 4, "overall": 4
        })
        result = coffee_rating(coffee_id, conn)
        # quality = (4 + 4 + 8) / 4 = 4.0 → Excellent
        assert result["tier"] == "Excellent"

    def test_very_good_tier(self, tmp_db):
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed(conn, scores={
            "aroma": 3, "acidity": 3, "sweetness": 3, "body": 3, "balance": 3, "overall": 3
        })
        result = coffee_rating(coffee_id, conn)
        # quality = (3 + 3 + 6) / 4 = 3.0 → Very Good
        assert result["tier"] == "Very Good"

    def test_good_tier(self, tmp_db):
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed(conn, scores={
            "aroma": 2, "acidity": 3, "sweetness": 2, "body": 2, "balance": 3, "overall": 2
        })
        result = coffee_rating(coffee_id, conn)
        # quality = (2 + 3 + 4) / 4 = 2.25 → Good
        assert result["tier"] == "Good"

    def test_below_average_tier(self, tmp_db):
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed(conn, scores={
            "aroma": 1, "acidity": 1, "sweetness": 1, "body": 2, "balance": 2, "overall": 1
        })
        result = coffee_rating(coffee_id, conn)
        # quality = (1 + 2 + 2) / 4 = 1.25 → Below Average
        assert result["tier"] == "Below Average"

    def test_profile_bright_when_acidity_high(self, tmp_db):
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed(conn, scores={
            "aroma": 3, "acidity": 5, "sweetness": 3, "body": 3, "balance": 3, "overall": 3
        })
        result = coffee_rating(coffee_id, conn)
        assert "Bright" in result["profile"]

    def test_profile_neutral_when_no_standouts(self, tmp_db):
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed(conn, scores={
            "aroma": 3, "acidity": 3, "sweetness": 3, "body": 3, "balance": 3, "overall": 3
        })
        result = coffee_rating(coffee_id, conn)
        assert result["profile"] == "Neutral profile"

    def test_sample_count_n(self, tmp_db):
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed(conn)
        result = coffee_rating(coffee_id, conn)
        assert result["n"] == 1

    def test_quality_with_taste_preferences(self, tmp_db):
        """Taste preferences should shift quality score."""
        conn = self._make_conn(tmp_db)
        # High sweetness preference + high sweetness score = boost
        coffee_id = self._seed(conn, scores={
            "aroma": 3, "acidity": 3, "sweetness": 5, "body": 3, "balance": 3, "overall": 3
        })
        set_setting(conn, "taste_preferences", json.dumps({
            "sweetness": 5, "acidity": 3, "body": 3, "aroma": 3
        }))
        conn.commit()
        result = coffee_rating(coffee_id, conn)
        # quality = (balance=3 + 2*overall=6 + 1.0*sweetness=5) / (3+1) = 14/4 = 3.5
        assert result["quality"] > 3.0  # should be boosted above default

    def test_quality_clamped_at_boundaries(self, tmp_db):
        """Quality score should never exceed 1-5 range even with extreme preferences."""
        conn = self._make_conn(tmp_db)
        # All dimensions 1 (low), preferences set to 1 (dislike) → negative weight on low scores
        coffee_id = self._seed(conn, scores={
            "aroma": 1, "acidity": 1, "sweetness": 1, "body": 1, "balance": 1, "overall": 1
        })
        set_setting(conn, "taste_preferences", json.dumps({
            "sweetness": 1, "acidity": 1, "body": 1, "aroma": 1
        }))
        conn.commit()
        result = coffee_rating(coffee_id, conn)
        assert result["quality"] >= 1.0
        assert result["quality"] <= 5.0

    def test_quality_negative_preference_hurts(self, tmp_db):
        """A dimension the user dislikes should lower quality when scored high."""
        conn = self._make_conn(tmp_db)
        coffee_id_high_acid = self._seed(conn, scores={
            "aroma": 3, "acidity": 5, "sweetness": 3, "body": 3, "balance": 3, "overall": 3
        })
        coffee_id_low_acid = self._seed(conn, scores={
            "aroma": 3, "acidity": 1, "sweetness": 3, "body": 3, "balance": 3, "overall": 3
        })
        # User dislikes acidity
        set_setting(conn, "taste_preferences", json.dumps({
            "sweetness": 3, "acidity": 1, "body": 3, "aroma": 3
        }))
        conn.commit()
        high_acid = coffee_rating(coffee_id_high_acid, conn)
        low_acid = coffee_rating(coffee_id_low_acid, conn)
        # Dislike acidity + high acidity → lower quality
        assert high_acid["quality"] < low_acid["quality"]


class TestRenderTastingNotes:
    def test_empty_string_returns_empty_list(self):
        assert render_tasting_notes("") == []

    def test_none_returns_empty_list(self):
        assert render_tasting_notes(None) == []

    def test_known_note_gets_emoji(self):
        result = render_tasting_notes("chocolate")
        assert len(result) == 1
        assert "🍫" in result[0]
        assert "chocolate" in result[0]

    def test_unknown_note_has_no_emoji(self):
        result = render_tasting_notes("mystery flavor")
        assert result == ["mystery flavor"]

    def test_multiple_notes(self):
        result = render_tasting_notes("chocolate, lemon")
        assert len(result) == 2

    def test_strips_whitespace_around_notes(self):
        result = render_tasting_notes("  chocolate  ,  honey  ")
        assert any("chocolate" in r for r in result)
        assert any("honey" in r for r in result)

    def test_case_insensitive_emoji_lookup(self):
        result = render_tasting_notes("Chocolate")
        assert "🍫" in result[0]

    def test_cherry_gets_correct_emoji(self):
        result = render_tasting_notes("cherry")
        assert "🍒" in result[0]

    def test_single_note_no_trailing_comma(self):
        result = render_tasting_notes("honey")
        assert len(result) == 1

    def test_empty_segment_from_double_comma_ignored(self):
        # "a,,b" should yield two notes, not three
        result = render_tasting_notes("chocolate,,honey")
        assert len(result) == 2


# ===========================================================================
# 3. ROUTE BEHAVIOUR
# ===========================================================================

class TestRouteCoffeeAdd:
    def test_post_redirects_302(self, client):
        resp = _add_coffee(client)
        assert resp.status_code == 302

    def test_redirect_goes_to_sample_route(self, client):
        resp = _add_coffee(client)
        assert "/sample/" in resp.headers["Location"]

    def test_adds_coffee_to_db(self, client, tmp_db):
        _add_coffee(client, roaster="Route Test Roaster")
        conn = _get_db(tmp_db)
        row = conn.execute("SELECT * FROM coffees WHERE roaster='Route Test Roaster'").fetchone()
        assert row is not None


class TestRouteSampleAdd:
    def _coffee_id(self, tmp_db):
        conn = _get_db(tmp_db)
        cur = conn.execute("INSERT INTO coffees (label) VALUES (?)", ("Sample Route Coffee",))
        conn.commit()
        return cur.lastrowid

    def test_add_sample_creates_record_and_redirects(self, client, tmp_db):
        coffee_id = self._coffee_id(tmp_db)
        resp = client.post(f"/sample/{coffee_id}/add", data={
            "grind_size": "19",
            "grams_in": "18",
            "grams_out": "36",
            "brew_min": "0",
            "brew_sec": "27",
        })
        assert resp.status_code == 302
        assert "/evaluate/" in resp.headers["Location"]

    def test_add_sample_persists(self, client, tmp_db):
        coffee_id = self._coffee_id(tmp_db)
        client.post(f"/sample/{coffee_id}/add", data={
            "grind_size": "20",
            "grams_in": "18",
            "grams_out": "36",
            "brew_min": "0",
            "brew_sec": "30",
        })
        conn = _get_db(tmp_db)
        row = conn.execute("SELECT * FROM samples WHERE coffee_id=?", (coffee_id,)).fetchone()
        assert row is not None
        assert row["grind_size"] == 20.0


class TestRouteEvaluateSave:
    def _seed(self, tmp_db):
        conn = _get_db(tmp_db)
        cur = conn.execute("INSERT INTO coffees (label) VALUES (?)", ("Evaluate Route Coffee",))
        coffee_id = cur.lastrowid
        cur2 = conn.execute(
            "INSERT INTO samples (coffee_id, grind_size, grams_in, grams_out, brew_time_sec) VALUES (?,?,?,?,?)",
            (coffee_id, 18, 18, 36, 28),
        )
        sample_id = cur2.lastrowid
        conn.commit()
        return coffee_id, sample_id

    def test_save_evaluation_returns_200(self, client, tmp_db):
        _, sample_id = self._seed(tmp_db)
        resp = client.post(f"/evaluate/{sample_id}/save", data={
            "aroma": "4", "acidity": "3", "sweetness": "4",
            "body": "3", "balance": "4", "overall": "4",
        })
        assert resp.status_code == 200

    def test_save_evaluation_with_representative_flag(self, client, tmp_db):
        _, sample_id = self._seed(tmp_db)
        client.post(f"/evaluate/{sample_id}/save", data={
            "aroma": "5", "acidity": "5", "sweetness": "5",
            "body": "5", "balance": "5", "overall": "5",
            "representative": "on",
        })
        conn = _get_db(tmp_db)
        row = conn.execute("SELECT representative FROM evaluations WHERE sample_id=?", (sample_id,)).fetchone()
        assert row["representative"] == 1

    def test_save_evaluation_invalid_sample_redirects(self, client, tmp_db):
        resp = client.post("/evaluate/99999/save", data={
            "aroma": "3", "acidity": "3", "sweetness": "3",
            "body": "3", "balance": "3", "overall": "3",
        })
        assert resp.status_code == 302

    def test_save_evaluation_with_no_scores(self, client, tmp_db):
        """Submitting the eval form without selecting any radio buttons should not crash."""
        _, sample_id = self._seed(tmp_db)
        resp = client.post(f"/evaluate/{sample_id}/save", data={})
        assert resp.status_code == 200


class TestGrindSmellPrefill:
    def _seed_coffee(self, tmp_db):
        conn = _get_db(tmp_db)
        cur = conn.execute("INSERT INTO coffees (label) VALUES (?)", ("Prefill Test",))
        conn.commit()
        return cur.lastrowid

    def test_add_sample_passes_grind_smell_in_redirect(self, client, tmp_db):
        coffee_id = self._seed_coffee(tmp_db)
        resp = client.post(f"/sample/{coffee_id}/add", data={
            "grind_size": "18", "grams_in": "18", "grams_out": "36",
            "brew_min": "0", "brew_sec": "28",
            "grind_smell": ["Fruity", "Nutty"],
        })
        assert resp.status_code == 302
        loc = resp.headers["Location"]
        assert "grind_smell=Fruity" in loc or "grind_smell=Fruity%2CNutty" in loc

    def test_evaluate_page_shows_prefilled_chips(self, client, tmp_db):
        coffee_id = self._seed_coffee(tmp_db)
        conn = _get_db(tmp_db)
        cur = conn.execute(
            "INSERT INTO samples (coffee_id, grind_size, grams_in, grams_out, brew_time_sec) VALUES (?,?,?,?,?)",
            (coffee_id, 18, 18, 36, 28))
        sample_id = cur.lastrowid
        conn.commit()
        resp = client.get(f"/evaluate/{sample_id}?grind_smell=Fruity,Nutty")
        assert resp.status_code == 200
        # Chips should be pre-selected (have 'active' class and 'checked')
        assert b"Fruity" in resp.data

    def test_grind_smell_not_stored_in_samples(self, client, tmp_db):
        coffee_id = self._seed_coffee(tmp_db)
        client.post(f"/sample/{coffee_id}/add", data={
            "grind_size": "18", "grams_in": "18", "grams_out": "36",
            "brew_min": "0", "brew_sec": "28",
            "grind_smell": ["Fruity", "Nutty"],
        })
        conn = _get_db(tmp_db)
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(samples)").fetchall()]
        if "grind_smell" in cols:
            row = conn.execute("SELECT grind_smell FROM samples").fetchone()
            assert row["grind_smell"] is None
        # Column may not exist at all in fresh DBs — that's also correct


class TestEditSampleValidation:
    def _seed(self, tmp_db):
        conn = _get_db(tmp_db)
        cur = conn.execute("INSERT INTO coffees (label) VALUES (?)", ("Edit Test",))
        coffee_id = cur.lastrowid
        cur2 = conn.execute(
            "INSERT INTO samples (coffee_id, grind_size, grams_in, grams_out, brew_time_sec) VALUES (?,?,?,?,?)",
            (coffee_id, 18, 18, 36, 28))
        sample_id = cur2.lastrowid
        conn.commit()
        return coffee_id, sample_id

    def test_move_to_nonexistent_coffee_redirects(self, client, tmp_db):
        coffee_id, sample_id = self._seed(tmp_db)
        resp = client.post(f"/sample/{sample_id}/edit", data={
            "coffee_id": "99999",
            "grind_size": "18", "grams_in": "18", "grams_out": "36",
            "brew_sec": "28", "brew_temp_c": "91",
        })
        assert resp.status_code == 302
        assert f"/sample/{coffee_id}" in resp.headers["Location"]


class TestRouteAutocomplete:
    def test_autocomplete_returns_json(self, client, tmp_db):
        resp = client.get("/api/autocomplete")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, dict)

    def test_autocomplete_has_expected_fields(self, client, tmp_db):
        resp = client.get("/api/autocomplete")
        data = resp.get_json()
        for field in ["roaster", "origin_country", "origin_city", "origin_producer", "variety"]:
            assert field in data
        assert "process" not in data  # process is a dropdown, not autocomplete

    def test_autocomplete_returns_unique_values(self, client, tmp_db):
        _add_coffee(client, roaster="AutoA", variety="V1", process="P1")
        _add_coffee(client, roaster="AutoA", variety="V2", process="P2")  # same roaster
        resp = client.get("/api/autocomplete")
        data = resp.get_json()
        assert data["roaster"].count("AutoA") == 1

    def test_autocomplete_empty_db_returns_empty_lists(self, client, tmp_db):
        resp = client.get("/api/autocomplete")
        data = resp.get_json()
        for field in ["roaster", "origin_country", "origin_city", "origin_producer", "variety"]:
            assert data[field] == []


class TestRouteInsights:
    """Tests for /insights — filters, findings, charts, and edge cases."""

    def _seed_coffee_with_eval(self, tmp_db, process="Washed", origin="Ethiopia",
                                variety="Bourbon", bean_color="Medium", bag_price=None,
                                bag_weight_g=None,
                                grind=18.0, overall=4, acidity=3, sweetness=4, body=3,
                                balance=4, aroma=4, representative=0):
        """Insert a coffee + sample + evaluation, return (coffee_id, sample_id)."""
        conn = _get_db(tmp_db)
        cur = conn.execute(
            """INSERT INTO coffees (label, process, origin_country, variety, bean_color,
                                    bag_price, bag_weight_g, roast_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, '2025-01-01')""",
            (f"{process} {origin} {variety}", process, origin, variety, bean_color, bag_price, bag_weight_g),
        )
        coffee_id = cur.lastrowid
        cur2 = conn.execute(
            "INSERT INTO samples (coffee_id, grind_size, grams_in, grams_out, brew_time_sec) VALUES (?,?,?,?,?)",
            (coffee_id, grind, 18, 36, 28),
        )
        sample_id = cur2.lastrowid
        conn.execute(
            """INSERT INTO evaluations (sample_id, aroma, acidity, sweetness, body, balance,
                                        overall, representative)
               VALUES (?,?,?,?,?,?,?,?)""",
            (sample_id, aroma, acidity, sweetness, body, balance, overall, representative),
        )
        conn.commit()
        return coffee_id, sample_id

    def _add_extra_shot(self, tmp_db, coffee_id, grind=18.0, overall=4, acidity=3,
                         sweetness=4, body=3, balance=4, aroma=4, representative=0):
        """Add another sample + evaluation to an existing coffee."""
        conn = _get_db(tmp_db)
        cur = conn.execute(
            "INSERT INTO samples (coffee_id, grind_size, grams_in, grams_out, brew_time_sec) VALUES (?,?,?,?,?)",
            (coffee_id, grind, 18, 36, 28),
        )
        sample_id = cur.lastrowid
        conn.execute(
            """INSERT INTO evaluations (sample_id, aroma, acidity, sweetness, body, balance,
                                        overall, representative)
               VALUES (?,?,?,?,?,?,?,?)""",
            (sample_id, aroma, acidity, sweetness, body, balance, overall, representative),
        )
        conn.commit()
        return sample_id

    # --- Basic rendering ---

    def test_insights_empty_db(self, client, tmp_db):
        resp = client.get("/insights")
        assert resp.status_code == 200
        assert b"Insights" in resp.data

    def test_insights_renders_with_data(self, client, tmp_db):
        self._seed_coffee_with_eval(tmp_db)
        resp = client.get("/insights")
        assert resp.status_code == 200
        assert b"Key Findings" in resp.data

    # --- Shot count accuracy ---

    def test_shot_count_reflects_total(self, client, tmp_db):
        cid, _ = self._seed_coffee_with_eval(tmp_db, overall=3)
        self._add_extra_shot(tmp_db, cid, overall=5)
        resp = client.get("/insights")
        assert b"2 shots" in resp.data

    def test_shot_count_changes_with_min_score(self, client, tmp_db):
        cid, _ = self._seed_coffee_with_eval(tmp_db, overall=2)
        self._add_extra_shot(tmp_db, cid, overall=5)
        # No filter: 2 shots
        resp = client.get("/insights")
        assert b"2 shots" in resp.data
        # min=4: only the overall=5 shot survives
        resp = client.get("/insights?min=4")
        assert b"1 shot" in resp.data
        assert b"2 shots" not in resp.data

    # --- Representative filter ---

    def test_rep_filter_excludes_non_representative(self, client, tmp_db):
        cid, _ = self._seed_coffee_with_eval(tmp_db, overall=3, representative=0)
        self._add_extra_shot(tmp_db, cid, overall=5, representative=1)
        # rep=1: only the representative shot
        resp = client.get("/insights?rep=1")
        assert b"1 shot" in resp.data

    def test_rep_filter_off_includes_all(self, client, tmp_db):
        cid, _ = self._seed_coffee_with_eval(tmp_db, overall=3, representative=0)
        self._add_extra_shot(tmp_db, cid, overall=5, representative=1)
        resp = client.get("/insights?rep=0")
        assert b"2 shots" in resp.data

    # --- Min score filter affects findings ---

    def test_min_score_excludes_coffee_with_no_qualifying_shots(self, client, tmp_db):
        self._seed_coffee_with_eval(tmp_db, process="Washed", overall=2)
        self._seed_coffee_with_eval(tmp_db, process="Natural", overall=5, origin="Colombia", variety="Caturra")
        # min=4: only the Natural coffee survives
        resp = client.get("/insights?min=4")
        assert b"Natural" in resp.data
        assert b"Washed" not in resp.data

    def test_min_score_zero_shows_all(self, client, tmp_db):
        self._seed_coffee_with_eval(tmp_db, process="Washed", overall=2)
        self._seed_coffee_with_eval(tmp_db, process="Natural", overall=5, origin="Colombia", variety="Caturra")
        resp = client.get("/insights?min=0")
        assert b"Washed" in resp.data
        assert b"Natural" in resp.data

    # --- Findings content ---

    def test_top_rated_finding(self, client, tmp_db):
        self._seed_coffee_with_eval(tmp_db, overall=5)
        resp = client.get("/insights")
        assert b"Top rated:" in resp.data

    def test_process_finding_shows_avg(self, client, tmp_db):
        self._seed_coffee_with_eval(tmp_db, process="Washed", overall=4)
        resp = client.get("/insights")
        assert b"Washed:" in resp.data
        assert b"avg" in resp.data

    def test_process_finding_shows_grind_as_float(self, client, tmp_db):
        self._seed_coffee_with_eval(tmp_db, process="Washed", grind=15.5, overall=4)
        resp = client.get("/insights")
        assert b"15.5" in resp.data

    def test_flavor_findings_present(self, client, tmp_db):
        self._seed_coffee_with_eval(tmp_db)
        resp = client.get("/insights")
        assert b"Sweetest:" in resp.data
        assert b"Brightest:" in resp.data
        assert b"Fullest body:" in resp.data

    def test_cross_cutting_finding_for_high_scoring(self, client, tmp_db):
        self._seed_coffee_with_eval(tmp_db, process="Natural", origin="Ethiopia",
                                     variety="Heirloom", overall=5)
        resp = client.get("/insights")
        assert b"Natural Ethiopia Heirloom" in resp.data

    def test_cross_cutting_absent_for_low_scoring(self, client, tmp_db):
        self._seed_coffee_with_eval(tmp_db, process="Natural", origin="Ethiopia",
                                     variety="Heirloom", overall=2)
        resp = client.get("/insights")
        # Cross section only shows coffees with avg >= 4.0
        assert b"Cross" not in resp.data or b"Natural Ethiopia Heirloom" not in resp.data

    def test_cross_cutting_null_fields_show_unknown(self, client, tmp_db):
        conn = _get_db(tmp_db)
        cur = conn.execute("INSERT INTO coffees (label) VALUES (?)", ("Mystery",))
        cid = cur.lastrowid
        cur2 = conn.execute(
            "INSERT INTO samples (coffee_id, grind_size, grams_in, grams_out, brew_time_sec) VALUES (?,?,?,?,?)",
            (cid, 18, 18, 36, 28))
        sid = cur2.lastrowid
        conn.execute(
            "INSERT INTO evaluations (sample_id, aroma, acidity, sweetness, body, balance, overall) VALUES (?,?,?,?,?,?,?)",
            (sid, 5, 5, 5, 5, 5, 5))
        conn.commit()
        resp = client.get("/insights")
        assert b"None" not in resp.data

    def test_roast_finding_with_two_roast_levels(self, client, tmp_db):
        self._seed_coffee_with_eval(tmp_db, bean_color="Light", overall=4)
        self._seed_coffee_with_eval(tmp_db, bean_color="Dark", overall=3,
                                     origin="Colombia", variety="Caturra")
        resp = client.get("/insights")
        assert b"Light roasts:" in resp.data
        assert b"Dark roasts:" in resp.data

    def test_value_finding_with_two_priced_coffees(self, client, tmp_db):
        self._seed_coffee_with_eval(tmp_db, bag_price=10, bag_weight_g=250, overall=4)
        self._seed_coffee_with_eval(tmp_db, bag_price=30, bag_weight_g=250, overall=3,
                                     origin="Colombia", variety="Caturra")
        resp = client.get("/insights")
        assert b"Best value:" in resp.data
        assert b"/shot" in resp.data

    def test_value_finding_absent_with_one_priced(self, client, tmp_db):
        self._seed_coffee_with_eval(tmp_db, bag_price=10, bag_weight_g=250, overall=4)
        resp = client.get("/insights")
        # Value requires >= 2 priced coffees
        assert b"Best value:" not in resp.data

    # --- Combined filters ---

    def test_rep_and_min_score_combined(self, client, tmp_db):
        cid, _ = self._seed_coffee_with_eval(tmp_db, overall=2, representative=0)
        self._add_extra_shot(tmp_db, cid, overall=5, representative=1)
        self._add_extra_shot(tmp_db, cid, overall=3, representative=1)
        # rep=1 & min=4: only the overall=5 representative shot
        resp = client.get("/insights?rep=1&min=4")
        assert b"1 shot" in resp.data

    # --- Empty results with filter ---

    def test_min_score_too_high_shows_empty(self, client, tmp_db):
        self._seed_coffee_with_eval(tmp_db, overall=2)
        resp = client.get("/insights?min=4")
        assert resp.status_code == 200
        # No findings, no crash
        assert b"Key Findings" not in resp.data


class TestRouteQuit:
    def test_quit_does_not_crash(self, client):
        with patch("app.os.system") as mock_sys:
            resp = client.post("/quit")
        assert resp.status_code == 200

    def test_quit_calls_pkill(self, client):
        with patch("app.subprocess.Popen") as mock_popen:
            client.post("/quit")
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert "chromium" in " ".join(args)

    def test_quit_returns_html(self, client):
        with patch("app.subprocess.Popen"):
            resp = client.post("/quit")
        assert b"html" in resp.data.lower()
