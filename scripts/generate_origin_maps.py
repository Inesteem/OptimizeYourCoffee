#!/usr/bin/env python3
"""Generate small SVG continent maps with highlighted coffee-origin countries.

Usage:
    python3 scripts/generate_origin_maps.py

Output:
    coffee-app/static/maps/<country-slug>.svg  (one per coffee-producing country)
    coffee-app/static/maps/origin-map-index.json  (country name → filename mapping)

Requirements:
    pip install geopandas matplotlib

Data source:
    Natural Earth 110m (simplified country boundaries, public domain)
    https://www.naturalearthdata.com/downloads/110m-cultural-vectors/
"""

import json
import re
from pathlib import Path

import geopandas as gpd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Where to write output
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
OUTPUT_DIR = PROJECT_ROOT / "coffee-app" / "static" / "maps"

# Natural Earth 110m — most simplified, tiny geometries
NE_URL = "https://naciscdn.org/naturalearth/110m/cultural/ne_110m_admin_0_countries.zip"

# Coffee-producing countries grouped by display region.
# Keys must match Natural Earth NAME column (or aliases handled below).
COFFEE_COUNTRIES = [
    # Africa
    "Ethiopia", "Kenya", "Tanzania", "Rwanda", "Burundi", "Uganda",
    "Dem. Rep. Congo", "Cameroon", "Ivory Coast", "Nigeria", "Malawi",
    "Zambia", "Zimbabwe", "Madagascar",
    # South America
    "Brazil", "Colombia", "Peru", "Ecuador", "Bolivia", "Venezuela",
    "Guyana", "Suriname",
    # Central America & Caribbean
    "Guatemala", "Honduras", "El Salvador", "Nicaragua", "Costa Rica",
    "Panama", "Mexico", "Jamaica", "Cuba", "Dominican Rep.", "Haiti",
    "Puerto Rico",
    # Asia & Oceania
    "Indonesia", "Vietnam", "India", "China", "Myanmar", "Thailand",
    "Laos", "Philippines", "Nepal", "Yemen", "Papua New Guinea",
    "Timor-Leste",
]

# Continents to render — maps Natural Earth CONTINENT to a display region
# that we want to crop to. Some NE continents are split for better framing.
REGION_DEFS = {
    "Africa": {
        "continents": ["Africa"],
    },
    "South America": {
        "continents": ["South America"],
    },
    "Central America": {
        # NE puts Central America + Caribbean under "North America"
        "continents": ["North America"],
        # Crop to just the relevant area (exclude Canada/US)
        "bounds": (-120, -60, 0, 35),  # (minx, miny, maxx, maxy) — approximate
    },
    "Asia": {
        "continents": ["Asia", "Oceania"],
        # Exclude far-east Pacific islands for cleaner framing
        "bounds": (25, -15, 155, 55),
    },
}

# User input aliases → Natural Earth NAME
ALIASES = {
    "Congo": "Dem. Rep. Congo",
    "DRC": "Dem. Rep. Congo",
    "DR Congo": "Dem. Rep. Congo",
    "Kenia": "Kenya",
    "Cote d'Ivoire": "Ivory Coast",
    "Côte d'Ivoire": "Ivory Coast",
    "Dominican Republic": "Dominican Rep.",
    "East Timor": "Timor-Leste",
    "Burma": "Myanmar",
    "PNG": "Papua New Guinea",
}

# SVG styling
BG_COLOR = "none"
CONTINENT_COLOR = "#444444"
HIGHLIGHT_COLOR = "#cc3333"
STROKE_COLOR = "#222222"
STROKE_WIDTH = 0.3

# Output SVG viewBox size (aspect ratio adjusted per continent)
SVG_HEIGHT = 80  # px target height


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slugify(name):
    """Convert country name to a filesystem-safe slug."""
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def country_to_region(country_name, world):
    """Find which display region a country belongs to."""
    row = world[world["NAME"] == country_name]
    if row.empty:
        return None
    ne_continent = row.iloc[0]["CONTINENT"]

    for region_name, rdef in REGION_DEFS.items():
        if ne_continent in rdef["continents"]:
            # Check bounds filter if present
            if "bounds" in rdef:
                centroid = row.iloc[0].geometry.centroid
                minx, miny, maxx, maxy = rdef["bounds"]
                if minx <= centroid.x <= maxx and miny <= centroid.y <= maxy:
                    return region_name
            else:
                return region_name
    return None


def get_region_countries(region_name, world):
    """Get all countries in a display region (for background rendering)."""
    rdef = REGION_DEFS[region_name]
    mask = world["CONTINENT"].isin(rdef["continents"])
    subset = world[mask]

    if "bounds" in rdef:
        minx, miny, maxx, maxy = rdef["bounds"]
        subset = subset.cx[minx:maxx, miny:maxy]

    return subset


def geometry_to_svg_path(geom, transform):
    """Convert a shapely geometry to SVG path d attribute."""
    from shapely.geometry import MultiPolygon, Polygon

    paths = []
    if isinstance(geom, Polygon):
        polys = [geom]
    elif isinstance(geom, MultiPolygon):
        polys = list(geom.geoms)
    else:
        return ""

    for poly in polys:
        # Exterior ring
        coords = list(poly.exterior.coords)
        if len(coords) < 3:
            continue
        parts = []
        for i, (x, y) in enumerate(coords):
            tx, ty = transform(x, y)
            if i == 0:
                parts.append(f"M{tx:.0f} {ty:.0f}")
            else:
                parts.append(f"L{tx:.0f} {ty:.0f}")
        parts.append("Z")
        paths.append(" ".join(parts))

    return " ".join(paths)


def render_svg(region_countries, highlight_name):
    """Render an SVG of the region with one country highlighted.

    The viewBox zooms toward the highlighted country so small countries
    (Costa Rica, Rwanda) are clearly visible instead of being tiny dots
    on a wide continent map. Large countries use the full region bounds.
    """
    # Region bounds and highlighted country bounds
    total_bounds = region_countries.total_bounds  # [minx, miny, maxx, maxy]
    highlight_row = region_countries[region_countries["NAME"] == highlight_name]

    if not highlight_row.empty:
        hb = highlight_row.total_bounds  # highlighted country bounds
        rb = total_bounds               # full region bounds

        # How much of the region does the country span? (area ratio of bounding boxes)
        h_area = max((hb[2] - hb[0]) * (hb[3] - hb[1]), 0.01)
        r_area = max((rb[2] - rb[0]) * (rb[3] - rb[1]), 0.01)
        ratio = h_area / r_area

        # Small countries: zoom in with generous context padding
        # Large countries: show full region
        if ratio < 0.02:
            # Very small (Costa Rica, Rwanda, El Salvador) — tight zoom
            context = 6.0  # country width × 6 on each side
        elif ratio < 0.08:
            # Small-medium (Guatemala, Kenya) — moderate zoom
            context = 4.0
        elif ratio < 0.25:
            # Medium (Colombia, Ethiopia) — slight zoom
            context = 2.5
        else:
            # Large (Brazil, Indonesia) — full region
            context = 0

        if context > 0:
            hw = hb[2] - hb[0]  # highlighted country width
            hh = hb[3] - hb[1]  # highlighted country height
            cx = (hb[0] + hb[2]) / 2  # center x
            cy = (hb[1] + hb[3]) / 2  # center y
            span = max(hw, hh) * context
            minx = cx - span / 2
            maxx = cx + span / 2
            miny = cy - span / 2
            maxy = cy + span / 2
        else:
            minx, miny, maxx, maxy = total_bounds
    else:
        minx, miny, maxx, maxy = total_bounds

    pad_x = (maxx - minx) * 0.05
    pad_y = (maxy - miny) * 0.05
    minx -= pad_x
    maxx += pad_x
    miny -= pad_y
    maxy += pad_y

    geo_w = maxx - minx
    geo_h = maxy - miny
    aspect = geo_w / geo_h if geo_h > 0 else 1.5
    svg_h = SVG_HEIGHT
    svg_w = round(svg_h * aspect)

    def transform(x, y):
        """Map geo coords to SVG coords (flip y)."""
        tx = (x - minx) / geo_w * svg_w
        ty = (1 - (y - miny) / geo_h) * svg_h
        return tx, ty

    # Build SVG
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {svg_w} {svg_h}" '
        f'width="{svg_w}" height="{svg_h}">',
    ]

    # Background countries
    for _, row in region_countries.iterrows():
        name = row["NAME"]
        fill = HIGHLIGHT_COLOR if name == highlight_name else CONTINENT_COLOR
        d = geometry_to_svg_path(row.geometry, transform)
        if d:
            parts.append(
                f'<path d="{d}" fill="{fill}" stroke="{STROKE_COLOR}" '
                f'stroke-width="{STROKE_WIDTH}"/>'
            )

    parts.append("</svg>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("Loading Natural Earth 110m data...")
    world = gpd.read_file(NE_URL)
    print(f"  {len(world)} countries loaded")

    # Simplify geometries for tiny icon use (tolerance in degrees, ~0.2° ≈ 22km)
    world["geometry"] = world["geometry"].simplify(0.2, preserve_topology=True)
    print("  Geometries simplified")

    # Add Ivory Coast alias (NE uses "Côte d'Ivoire")
    civ = world[world["NAME"] == "Côte d'Ivoire"]
    if not civ.empty:
        world.loc[civ.index, "NAME"] = "Ivory Coast"

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Pre-compute region data
    region_cache = {}
    for rname in REGION_DEFS:
        region_cache[rname] = get_region_countries(rname, world)

    index = {}  # country name → svg filename
    generated = 0
    skipped = []

    for country in COFFEE_COUNTRIES:
        region = country_to_region(country, world)
        if region is None:
            skipped.append(country)
            continue

        region_countries = region_cache[region]
        svg_content = render_svg(region_countries, country)

        slug = slugify(country)
        filename = f"{slug}.svg"
        outpath = OUTPUT_DIR / filename
        outpath.write_text(svg_content)

        # Map both the canonical name and common aliases
        index[country.lower()] = filename
        for alias, canonical in ALIASES.items():
            if canonical == country:
                index[alias.lower()] = filename

        generated += 1
        print(f"  {country} → {filename} ({region})")

    # Write index
    index_path = OUTPUT_DIR / "origin-map-index.json"
    index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False))

    print(f"\nDone: {generated} maps generated, {len(skipped)} skipped")
    if skipped:
        print(f"  Skipped (not found in Natural Earth): {', '.join(skipped)}")
    print(f"  Index: {index_path}")
    print(f"  Maps:  {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
