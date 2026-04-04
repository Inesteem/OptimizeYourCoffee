#!/usr/bin/env python3
"""Resolve optimal altitude labels to meter ranges based on origin country latitude.

The coffee varieties catalog uses labels like "High", "Medium", "Low" for optimal
altitude. The actual meter range depends on the farm's latitude band (from the
altitude reference document). This script converts the label to a meter range
string for display in the app.

Usage:
    python3 scripts/resolve_altitude.py [--country COUNTRY]

Without --country: prints the lookup table for all coffee-producing countries.
With --country: resolves a specific country and prints the result for each
altitude label.

The resolved ranges are NOT written to coffee-info.json because the variety's
optimal altitude is independent of where it's grown — it's a property of the
variety that shifts with latitude. Instead, the app should resolve at display
time given the user's coffee origin.
"""

import argparse
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
COFFEE_INFO = PROJECT_ROOT / "coffee-app" / "static" / "coffee-info.json"

# Latitude bands for coffee-producing countries (approximate center latitude)
# Grouped by the altitude reference bands:
#   Equatorial: 5°N to 5°S
#   Tropical:   5-15°N or 5-15°S
#   Subtropical: >15°N or >15°S
COUNTRY_LATITUDES = {
    # Equatorial (0-5°)
    "ecuador": "equatorial",
    "colombia": "equatorial",      # 4°N center, spans both bands
    "kenya": "equatorial",         # ~1°S
    "uganda": "equatorial",        # ~1°N
    "dem. rep. congo": "equatorial",
    "congo": "equatorial",
    "rwanda": "equatorial",        # ~2°S
    "burundi": "equatorial",       # ~3°S
    "indonesia": "equatorial",     # Java/Sumatra ~0-5°S
    "papua new guinea": "equatorial",
    "timor-leste": "equatorial",   # ~8°S but high-altitude growing

    # Tropical (5-15°)
    "ethiopia": "tropical",        # ~8°N
    "costa rica": "tropical",      # ~10°N
    "panama": "tropical",          # ~8°N
    "nicaragua": "tropical",       # ~12°N
    "honduras": "tropical",        # ~14°N
    "el salvador": "tropical",     # ~14°N
    "guatemala": "tropical",       # ~15°N (borderline)
    "jamaica": "tropical",         # ~18°N (borderline subtropical)
    "vietnam": "tropical",         # ~12°N (central highlands)
    "india": "tropical",           # ~12°N (Karnataka/Kerala)
    "yemen": "tropical",           # ~15°N
    "laos": "tropical",            # ~15°N
    "thailand": "tropical",        # ~14°N (northern highlands)
    "philippines": "tropical",     # ~12°N
    "myanmar": "tropical",         # ~15°N (Shan state)
    "cameroon": "tropical",        # ~6°N
    "nigeria": "tropical",         # ~8°N
    "ivory coast": "tropical",     # ~7°N
    "tanzania": "tropical",        # ~6°S
    "malawi": "tropical",          # ~14°S
    "zambia": "tropical",          # ~13°S
    "madagascar": "tropical",      # ~15°S (borderline)

    # Subtropical (>15°)
    "brazil": "subtropical",       # ~15-23°S
    "mexico": "subtropical",       # ~18-22°N
    "peru": "subtropical",         # ~10°S but mostly >15°S growing
    "bolivia": "subtropical",      # ~17°S
    "cuba": "subtropical",         # ~22°N
    "dominican rep.": "subtropical",  # ~19°N
    "haiti": "subtropical",        # ~19°N
    "puerto rico": "subtropical",  # ~18°N
    "china": "subtropical",        # ~22°N (Yunnan)
    "nepal": "subtropical",        # ~28°N
    "zimbabwe": "subtropical",     # ~19°S
    "venezuela": "subtropical",    # ~8°N but mostly lowland
    "guyana": "subtropical",       # ~5°N
    "suriname": "subtropical",     # ~4°N
}

# Altitude label → meter range per latitude band
# From reference/altitude.md
ALTITUDE_RANGES = {
    "equatorial": {  # 5°N to 5°S
        "Low": "1000–1200m",
        "Low-medium": "1000–1600m",
        "Low , Medium": "1000–1600m",
        "Medium": "1200–1600m",
        "Medium-high": ">1200m",
        "Medium , High": ">1200m",
        "High": ">1600m",
        "High , Medium": ">1200m",
        "Low , Medium , High": ">1000m",
    },
    "tropical": {  # 5-15°
        "Low": "700–900m",
        "Low-medium": "700–1300m",
        "Low , Medium": "700–1300m",
        "Medium": "900–1300m",
        "Medium-high": ">900m",
        "Medium , High": ">900m",
        "High": ">1300m",
        "High , Medium": ">900m",
        "Low , Medium , High": ">700m",
    },
    "subtropical": {  # >15°
        "Low": "400–700m",
        "Low-medium": "400–1000m",
        "Low , Medium": "400–1000m",
        "Medium": "700–1000m",
        "Medium-high": ">700m",
        "Medium , High": ">700m",
        "High": ">1000m",
        "High , Medium": ">700m",
        "Low , Medium , High": ">400m",
    },
}


def resolve_altitude(altitude_label, country):
    """Resolve an altitude label to a meter range for a given country.

    Returns a string like ">1600m" or "900–1300m", or None if unknown.
    """
    if not altitude_label or altitude_label == "Not applicable":
        return None
    country_key = country.lower().strip() if country else None
    band = COUNTRY_LATITUDES.get(country_key, "tropical")  # default to tropical
    ranges = ALTITUDE_RANGES.get(band, ALTITUDE_RANGES["tropical"])
    return ranges.get(altitude_label)


def main():
    parser = argparse.ArgumentParser(description="Resolve altitude labels to meter ranges")
    parser.add_argument("--country", help="Resolve for a specific country")
    args = parser.parse_args()

    with open(COFFEE_INFO) as f:
        data = json.load(f)

    if args.country:
        band = COUNTRY_LATITUDES.get(args.country.lower(), "tropical")
        print(f"{args.country} → latitude band: {band}")
        print()
        for label in sorted(ALTITUDE_RANGES[band].keys()):
            print(f"  {label:25s} → {ALTITUDE_RANGES[band][label]}")
    else:
        # Show all varieties with their altitude labels
        varieties = data.get("varieties", {})
        for name, info in sorted(varieties.items()):
            alt = info.get("optimal_altitude")
            if alt and alt != "Not applicable":
                # Show resolution for Ethiopian origin as example
                resolved = resolve_altitude(alt, "Ethiopia")
                print(f"  {name:30s} {alt:25s} → {resolved} (tropical)")


if __name__ == "__main__":
    main()
