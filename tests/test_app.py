"""
Tests for the Coffee Sampler Flask app (coffee-app/app.py).

Run with:
    python3.11 -m pytest tests/        (from project root)
    pytest tests/                      (if pytest resolves to python3.11's pytest)
"""

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
    TASTING_EMOJIS,
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

    def test_add_coffee_default_best_after(self, client, tmp_db):
        _add_coffee(client, best_after_days="")
        conn = _get_db(tmp_db)
        row = conn.execute("SELECT * FROM coffees ORDER BY id DESC LIMIT 1").fetchone()
        assert row["best_after_days"] == 7

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
        coffee = _make_coffee_row(roast_date="2025-03-01", best_after_days=None, consume_within_days=50)
        fake_today = date(2025, 3, 9)  # 8 days after roast, default best_after=7
        with patch("app.date") as mock_date:
            mock_date.today.return_value = fake_today
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
            result = freshness_status(coffee)
        # day 8 > rest_end(7), <= peak_end(7+11=18) → peak
        assert result["stage"] == "peak"

    def test_days_field_is_correct(self):
        result = self._status(10)
        assert result["days"] == 10


class TestDiagnose:
    def test_under_extracted_full_pattern(self):
        tips = diagnose({"acidity": 5, "sweetness": 1, "body": 1, "balance": 3, "overall": 3})
        assert any("under-extracted" in t for t in tips)

    def test_high_acidity_low_sweetness(self):
        tips = diagnose({"acidity": 4, "sweetness": 2, "body": 3, "balance": 3, "overall": 3})
        assert any("finer" in t for t in tips)

    def test_over_extracted_pattern(self):
        tips = diagnose({"acidity": 1, "sweetness": 2, "body": 3, "balance": 3, "overall": 3})
        assert any("over-extracted" in t for t in tips)

    def test_thin_body_sweet(self):
        tips = diagnose({"acidity": 3, "sweetness": 4, "body": 1, "balance": 3, "overall": 3})
        assert any("Thin body" in t for t in tips)

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


class TestSuggestGrind:
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

    def test_no_data_returns_none(self, tmp_db):
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed_coffee(conn)
        result = suggest_grind(coffee_id, conn)
        assert result is None

    def test_one_shot_returns_low_confidence(self, tmp_db):
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed_coffee(conn)
        self._seed_shot(conn, coffee_id, 18.0, 4)
        result = suggest_grind(coffee_id, conn)
        assert result is not None
        assert result["confidence"] == "low"
        assert result["grind"] == 18.0

    def test_two_shots_returns_best_grind_low_confidence(self, tmp_db):
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed_coffee(conn)
        self._seed_shot(conn, coffee_id, 17.0, 3)
        self._seed_shot(conn, coffee_id, 19.0, 5)
        result = suggest_grind(coffee_id, conn)
        assert result["confidence"] == "low"
        assert result["grind"] == 19.0  # best shot

    def test_three_plus_shots_returns_result(self, tmp_db):
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed_coffee(conn)
        # Parabola peak near grind 20: scores go 3, 5, 3 at 18, 20, 22
        self._seed_shot(conn, coffee_id, 18.0, 3)
        self._seed_shot(conn, coffee_id, 20.0, 5)
        self._seed_shot(conn, coffee_id, 22.0, 3)
        result = suggest_grind(coffee_id, conn)
        assert result is not None
        assert "grind" in result
        assert "confidence" in result

    def test_six_plus_shots_medium_or_high_confidence(self, tmp_db):
        conn = self._make_conn(tmp_db)
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
        coffee_id = self._seed_coffee(conn)
        self._seed_shot(conn, coffee_id, 18.0, 3)
        result = suggest_grind(coffee_id, conn)
        assert "1 shot" in result["detail"]

    def test_detail_plural_shots(self, tmp_db):
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed_coffee(conn)
        self._seed_shot(conn, coffee_id, 17.0, 3)
        self._seed_shot(conn, coffee_id, 19.0, 4)
        result = suggest_grind(coffee_id, conn)
        assert "2 shots" in result["detail"]


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
        for key in ("tier", "css", "avg_taste", "avg_overall", "profile", "avgs", "n"):
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
        # avg_taste just at 3.8
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed(conn, scores={
            "aroma": 4, "acidity": 4, "sweetness": 4, "body": 4, "balance": 3, "overall": 4
        })
        result = coffee_rating(coffee_id, conn)
        # avg_taste = (4+4+4+4+3)/5 = 3.8 → Excellent
        assert result["tier"] == "Excellent"

    def test_very_good_tier(self, tmp_db):
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed(conn, scores={
            "aroma": 3, "acidity": 3, "sweetness": 3, "body": 3, "balance": 3, "overall": 3
        })
        result = coffee_rating(coffee_id, conn)
        assert result["tier"] == "Very Good"

    def test_good_tier(self, tmp_db):
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed(conn, scores={
            "aroma": 2, "acidity": 3, "sweetness": 2, "body": 2, "balance": 3, "overall": 2
        })
        result = coffee_rating(coffee_id, conn)
        # avg = (2+3+2+2+3)/5 = 2.4 → Good
        assert result["tier"] == "Good"

    def test_below_average_tier(self, tmp_db):
        conn = self._make_conn(tmp_db)
        coffee_id = self._seed(conn, scores={
            "aroma": 1, "acidity": 1, "sweetness": 1, "body": 2, "balance": 2, "overall": 1
        })
        result = coffee_rating(coffee_id, conn)
        # avg = (1+1+1+2+2)/5 = 1.4 → Below Average
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
