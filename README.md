# Coffee Sampler

A touchscreen espresso sampling app for Raspberry Pi with the official 7" display.

## Overview

Track espresso shots, evaluate flavors, and dial in your grind. Three-step workflow:

1. **Select or define a coffee** — roaster, origin, variety, process, bean color/size, tasting notes (emoji chips), roast date, opened date, freshness tracking, bag inventory, roaster's recipe defaults
2. **Log a brew sample** — grind size (with AI suggestion), dose in/out (with ratio deviation display), brew time, temperature, grind smell descriptors. Pre-filled from roaster's recipe.
3. **Evaluate the shot** — score aroma, acidity, sweetness, body, balance, overall (1-5 scale). Grind aroma, brew smell, and taste descriptor chips. Preheat tracking, milk flag, notes. Mark as representative. Automatic diagnostic feedback with grind adjustment recommendations.

## Screenshots

### Coffee List
Browse your coffee collection with freshness indicators, ratings, tasting note chips, origin maps, and bag tracking. Sort by roast date, rating, or days open.

![Coffee List](screenshots/01-coffee-list.png)

### Log a Sample
Record brew parameters for each shot. Grind size is pre-filled with an AI suggestion based on past performance. Dose, output, time, and temperature carry forward from the last shot or roaster's recipe.

![Sample Page](screenshots/02-sample-page.png)

### Evaluate the Shot
Score each flavor dimension (aroma, acidity, sweetness, body, balance, overall) on a 1-5 scale. Add taste descriptors as chips and get instant diagnostic feedback.

![Evaluate Shot](screenshots/03-evaluate.png)

### Per-Coffee Stats
Grind vs score scatter plot, score timeline, flavor radar, and key metrics for each coffee. Cross-coffee comparison with selectable metrics.

![Stats](screenshots/04-stats.png)

### Cross-Coffee Insights
Aggregate findings across all coffees grouped by process, origin, roast level, and flavor profile. Filter by representative shots and minimum score.

![Insights](screenshots/05-insights.png)

### Edit Coffee
Full coffee details form with origin map preview, variety and process info popups, tasting notes, roast date, freshness overrides, bag inventory, and default brew recipe.

![Edit Coffee](screenshots/06-edit-coffee.png)

### Settings

Four settings tabs for customizing the app:

| Tasting Notes | Grind Optimizer |
|:---:|:---:|
| ![Tasting Notes](screenshots/07-settings-notes.png) | ![Grind Optimizer](screenshots/08-settings-grind.png) |
| Manage custom emoji labels for tasting notes | Configure grind suggestion algorithm and parameters |

| Taste Profile | Card Design |
|:---:|:---:|
| ![Taste Profile](screenshots/09-settings-taste.png) | ![Card Design](screenshots/10-settings-design.png) |
| Set flavor preferences to weight coffee ratings | Choose coffee card layout style |

## Features

### Core
- **Freshness tracking** — 6-stage model (degassing -> resting -> peak -> good -> fading -> stale) with roast-level-dependent windows, opened date acceleration, and days-since-roast/opened per sample
- **Grind suggestion** — 3 selectable algorithms (weighted centroid, Bayesian quadratic, classic curve fit) plus ratio-directed search, with configurable score source, recipe-matching filter, and cross-coffee prior
- **Smart diagnostics** — taste descriptor-based extraction feedback (sour/thin/watery -> under-extracted, bitter/harsh/ashy -> over-extracted, channeling detection), brew time analysis, output deviation detection
- **Coffee ratings** — preference-weighted quality score from representative shots with tier labels (Outstanding/Excellent/Very Good/Good/Below Average) and auto-generated flavor profile descriptors

### Data & Visualization
- **Per-coffee stats** — grind vs score scatter, score timeline, flavor radar, cross-coffee comparison with metric picker
- **Cross-coffee insights** — findings organized by category (Process, Flavor, Roast, Cross-cutting, Value), charts by process/origin/roast level, flavor profile radar with toggle chips, forgiveness metric, price-per-shot value
- **Coffee info popups** — tappable variety and process names show description, flavor profile, species, and brewing tips from built-in database (20+ varieties, 16 processes)
- **Origin map icons** — 46 country silhouettes on continent maps, displayed on coffee cards
- **Output deviation** — real-time display of actual vs expected output based on coffee's ratio

### UX
- **Tasting notes** — emoji chip input with ~90 built-in notes, custom labels via settings, searchable emoji picker
- **Autocomplete** — inline suggestion chips for all text fields (from static lists + DB entries)
- **3-section evaluation descriptors** — grind smell, brew smell, taste notes (30+ chips including diagnostic negatives)
- **On-screen keyboard** — German umlauts, special characters, single-char shift toggle
- **Sample edit/move** — edit brew parameters, move samples between coffees
- **Open bag dialog** — prompts to set opened date when first sampling a coffee
- **Undo** — restore deleted coffees and samples with all evaluations
- **Archive** — hide empty bags, browse archived coffees
- **Card designs** — 3 selectable layouts (Modern, Showcase, Legacy)
- **Auto backup** — timestamped DB backup on every startup + before every deploy

## Stack

- **Backend**: Python 3 / Flask / SQLite (WAL mode)
- **Frontend**: HTML/CSS/JS, Chart.js, simple-keyboard
- **Display**: Chromium kiosk on Wayland (800x480 DSI touchscreen)
- **Grind optimization**: numpy (optional, quadratic regression) + pure Python (Bayesian, centroid)

## Hardware

- Raspberry Pi 4 Model B (8GB recommended)
- Official Raspberry Pi 7" capacitive touchscreen (800x480)
- Raspberry Pi OS 64-bit

> **First time?** See [SETUP.md](SETUP.md) for full installation guide.

## Deployment

```bash
# Safe deploy: backs up DB, stops Flask, syncs files, restarts
./deploy.sh
```

Requires `deploy.conf` (see `deploy.conf.example`).

## Files

```
coffee-app/
├── app.py                      # Flask application
├── coffee-kiosk.service        # systemd service template
├── restart-ui.sh               # Restart Flask + Chromium helper
├── static/
│   ├── style.css               # Dark theme CSS
│   ├── keyboard.js             # Virtual keyboard
│   ├── autocomplete.js         # Inline chip autocomplete
│   ├── tastingnotes.js         # Tasting note chip input
│   ├── coffeeinfo.js           # Variety/process info popups
│   ├── coffee-info.json        # Variety & process descriptions
│   ├── coffee-info-manual.json # Hand-curated variety overrides
│   ├── coffee-bean.svg         # Desktop icon
│   ├── varieties.json          # ~130 cultivar names
│   ├── maps/                   # SVG origin country map icons (46 countries)
│   ├── chart.min.js            # Chart.js library
│   ├── simple-keyboard.min.js  # Keyboard library
│   └── simple-keyboard.css
└── templates/
    ├── step1_coffee.html       # Coffee selection / creation
    ├── step2_sample.html       # Brew sample logging
    ├── step3_evaluate.html     # Shot evaluation + diagnostics
    ├── edit_coffee.html        # Edit coffee details
    ├── edit_sample.html        # Edit/move sample
    ├── open_bag.html           # Open bag dialog
    ├── stats.html              # Per-coffee charts
    ├── insights.html           # Cross-coffee insights
    ├── settings_notes.html     # Tasting note labels
    ├── settings_grind.html     # Grind optimizer config
    ├── settings_taste.html     # Taste preference weights
    └── settings_design.html    # Card design picker
```

## Database Schema

### coffees
| Column | Type | Description |
|--------|------|-------------|
| roaster, origin_country/city/producer | TEXT | Origin info |
| variety, process | TEXT | Bean variety and processing method |
| tasting_notes | TEXT | Comma-separated with emoji support |
| label | TEXT | Display label (auto-generated) |
| roast_date, opened_date | TEXT | Dates for freshness tracking |
| best_after_days, consume_within_days | INTEGER | Freshness config (roast-level defaults) |
| bean_color, bean_size | TEXT | Light/Medium/Dark, Small/Medium/Large/Peaberry |
| bag_weight_g, bag_price | REAL | Inventory (default 250g) |
| default_grams_in/out, default_brew_time_sec | REAL/INT | Roaster's recipe |
| archived | INTEGER | 0=active, 1=archived |

### samples
| Column | Type | Description |
|--------|------|-------------|
| coffee_id | INTEGER | FK to coffees |
| grind_size, grams_in, grams_out | REAL | Brew parameters |
| brew_time_sec | INTEGER | Time in seconds |
| brew_temp_c | REAL | Temperature (default 91C) |
| days_since_roast, days_since_opened | INTEGER | Snapshot at creation |
| notes | TEXT | Free-text brew notes |

### evaluations
| Column | Type | Description |
|--------|------|-------------|
| aroma, acidity, sweetness, body, balance, overall | INTEGER | 1-5 scores |
| grind_aroma | INTEGER | 1-5 grind smell intensity (captured on sample page, stored here) |
| aroma_descriptors, brew_smell_descriptors, taste_descriptors | TEXT | Comma-separated chips |
| preheat_portafilter/cup/machine | INTEGER | Preheat flags |
| with_milk | INTEGER | Consumed with milk |
| eval_notes | TEXT | Free-text notes |
| representative | INTEGER | Counts toward rating |

## Diagnostics

Automatic extraction feedback from taste descriptors + brew params:

| Signal | Detection | Feedback |
|--------|-----------|----------|
| Sour/Acidic/Thin/Watery | Under-extraction | Insufficient extraction |
| Bitter/Burned/Ashy/Dry/Harsh | Over-extraction | Too much extraction |
| Sour AND Bitter | Channeling | Fix puck prep (WDT, tamp) |
| Brew time <20s | Fast flow | Noted for reference |
| Brew time >35s | Slow flow/choked | Noted for reference |
| Output deviation >5g | Off-target | Noted for reference |

Grind size adjustments are handled by the grind optimizer (Settings -> Grind Optimizer).

## Known Chromium/Wayland Issues

- `position: fixed` with `display: none/block` won't repaint — use `:empty` collapse
- Cache aggressive — disabled via `--disk-cache-size=1`
- Asset versioning via Flask startup timestamp (`?v={{ v }}`)

## Reference

See `reference/` for domain knowledge:
- `coffee-varieties.md` — 60+ varieties, 16 processes, species taxonomy
- `coffee-freshness.md` — degradation science, storage impacts
- `coffee-rating-labels.md` — SCA scoring, tier mapping
- `espresso-evaluation.md` — scoring dimensions, diagnostic patterns
- `extraction-diagnostics.md` — taste-based extraction mapping
- `grind-optimization.md` — 4 grind algorithms, score sources, filters
- `tasting-note-labels.md` — emoji mappings, chip lists
- `altitude.md` — altitude label resolution by latitude

Variety and genetic data sourced from: [World Coffee Research Varieties Catalog](https://varieties.worldcoffeeresearch.org)
