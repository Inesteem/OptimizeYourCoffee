#!/usr/bin/env python3
"""Take full-page screenshots of all Coffee Sampler pages using Pi's real database.

Requirements: pip install selenium chromedriver-autoinstaller
Usage: scp the Pi database to /tmp/coffee-pi.db first, then run this script.
"""

import sys
import os
import time
import shutil
import sqlite3
import subprocess
import urllib.request

try:
    import chromedriver_autoinstaller
    chromedriver_autoinstaller.install()
except ImportError:
    print("Install chromedriver-autoinstaller: pip install chromedriver-autoinstaller")
    sys.exit(1)

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
except ImportError:
    print("Install selenium: pip install selenium")
    sys.exit(1)

# Config
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
APP_DIR = os.path.join(PROJECT_DIR, "coffee-app")
DB_SRC = "/tmp/coffee-pi.db"
DB_DST = os.path.join(APP_DIR, "coffee.db")
SCREENSHOT_DIR = os.path.join(PROJECT_DIR, "screenshots")
PORT = 5000
BASE_URL = f"http://localhost:{PORT}"
WIDTH = 800
INITIAL_HEIGHT = 480  # Start small so scrollHeight reflects real content


def get_content_height(driver):
    """Get the true content height by checking all relevant properties."""
    return driver.execute_script("""
        document.body.offsetHeight;
        return Math.max(
            document.body.scrollHeight,
            document.body.offsetHeight,
            document.documentElement.scrollHeight,
            document.documentElement.offsetHeight
        );
    """)


def screenshot(driver, url_path, filename, wait_for=None, sleep=1.5, max_height=None):
    """Navigate, resize to full content height, and take a screenshot."""
    url = BASE_URL + url_path
    print(f"  {filename}: {url}")

    # Load page at small viewport so scrollHeight reflects overflow
    driver.set_window_size(WIDTH, INITIAL_HEIGHT)
    driver.get(url)

    if wait_for:
        try:
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, wait_for))
            )
        except Exception:
            pass

    # Wait for charts/dynamic content
    time.sleep(sleep)

    # Measure content height at small viewport
    content_h = get_content_height(driver)

    # Expand viewport to full content height
    target_h = content_h + 40
    if max_height:
        target_h = min(target_h, max_height)
    target_h = max(target_h, INITIAL_HEIGHT)

    driver.set_window_size(WIDTH, target_h)
    time.sleep(0.8)

    # Re-measure after reflow — content may have shifted
    content_h2 = get_content_height(driver)
    if content_h2 > target_h:
        target_h = content_h2 + 40
        if max_height:
            target_h = min(target_h, max_height)
        driver.set_window_size(WIDTH, target_h)
        time.sleep(0.5)

    path = os.path.join(SCREENSHOT_DIR, filename)
    driver.save_screenshot(path)
    print(f"    -> saved ({WIDTH}x{target_h})")


def main():
    if not os.path.exists(DB_SRC):
        print(f"ERROR: Copy the Pi database to {DB_SRC} first:")
        print(f"  scp pi@<host>:~/coffee-app/coffee.db {DB_SRC}")
        sys.exit(1)

    os.makedirs(SCREENSHOT_DIR, exist_ok=True)

    # Backup existing DB if any
    db_backup = None
    if os.path.exists(DB_DST):
        db_backup = DB_DST + ".bak"
        shutil.copy2(DB_DST, db_backup)

    # Copy Pi DB
    shutil.copy2(DB_SRC, DB_DST)

    # Start Flask app
    env = os.environ.copy()
    env["FLASK_DEBUG"] = "0"
    flask_proc = subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=APP_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for server with retry
    print("Waiting for Flask to start...")
    for i in range(20):
        try:
            urllib.request.urlopen(BASE_URL, timeout=1)
            print("  Server is up!")
            break
        except Exception:
            time.sleep(0.5)
    else:
        print("ERROR: Flask didn't start.")
        flask_proc.terminate()
        sys.exit(1)

    # Setup Chrome
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument(f"--window-size={WIDTH},{INITIAL_HEIGHT}")
    options.add_argument("--force-device-scale-factor=1")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--hide-scrollbars")

    driver = webdriver.Chrome(options=options)

    # Find best coffee for detailed views
    conn = sqlite3.connect(DB_DST)
    conn.row_factory = sqlite3.Row
    row = conn.execute("""
        SELECT c.id FROM coffees c
        JOIN samples s ON s.coffee_id = c.id
        JOIN evaluations e ON e.sample_id = s.id
        WHERE c.archived = 0
        GROUP BY c.id ORDER BY COUNT(e.id) DESC LIMIT 1
    """).fetchone()
    coffee_id = row["id"]

    sample = conn.execute(
        "SELECT s.id FROM samples s JOIN evaluations e ON e.sample_id = s.id "
        "WHERE s.coffee_id = ? ORDER BY s.id DESC LIMIT 1",
        (coffee_id,)
    ).fetchone()
    sample_id = sample["id"]
    conn.close()

    print(f"Using coffee_id={coffee_id}, sample_id={sample_id}")

    try:
        print("Taking full-page screenshots...")

        screenshot(driver, "/", "01-coffee-list.png", wait_for=".coffee-card", sleep=2.5)
        screenshot(driver, f"/sample/{coffee_id}", "02-sample-page.png", wait_for="form", sleep=2)
        screenshot(driver, f"/evaluate/{sample_id}", "03-evaluate.png", wait_for="form", sleep=2)
        screenshot(driver, f"/stats/{coffee_id}", "04-stats.png", wait_for="canvas", sleep=3)
        screenshot(driver, "/insights", "05-insights.png", wait_for="canvas", sleep=3)
        screenshot(driver, f"/coffee/{coffee_id}/edit", "06-edit-coffee.png", wait_for="form", sleep=2)
        screenshot(driver, "/settings/tasting-notes", "07-settings-notes.png", wait_for="form", max_height=1200)
        screenshot(driver, "/settings/grind", "08-settings-grind.png", wait_for="form", sleep=2)
        screenshot(driver, "/settings/taste", "09-settings-taste.png", wait_for="form", sleep=2)
        screenshot(driver, "/settings/design", "10-settings-design.png", wait_for="form")

        print(f"\nAll screenshots saved to: {SCREENSHOT_DIR}")

    finally:
        driver.quit()
        flask_proc.terminate()
        flask_proc.wait(timeout=5)
        # Restore original DB
        if db_backup and os.path.exists(db_backup):
            shutil.move(db_backup, DB_DST)
        elif not db_backup:
            os.remove(DB_DST)


if __name__ == "__main__":
    main()
