# Coffee Sampler

A touchscreen coffee sampling app for Raspberry Pi with the official 7" display.

## Overview

Track espresso shots, evaluate flavors, and dial in your grind. Three-step workflow:

1. **Select or define a coffee** — roaster, origin, variety, process, tasting notes (emoji chips), roast date, freshness tracking, bag inventory, roaster's recipe defaults
2. **Log a brew sample** — grind size (with AI suggestion), dose in/out, brew time (seconds). Pre-filled from roaster's recipe.
3. **Evaluate the shot** — score aroma, acidity, sweetness, body, balance, overall (1–5 scale). Mark as representative. Automatic diagnostic feedback + freshness context.

## Features

- **Freshness tracking** — 6-stage model (degassing → resting → peak → good → fading → stale) based on roast date and configurable best-after/consume-within days
- **Grind suggestion** — quadratic regression on evaluation scores to suggest optimal grind size
- **Coffee ratings** — aggregate score from representative shots with tier labels (Outstanding/Excellent/Very Good/Good) and flavor profile descriptors
- **Tasting notes** — emoji chip input with ~90 built-in notes, custom labels via settings, searchable emoji picker
- **Autocomplete** — inline suggestion chips for roaster, country, city, producer, variety (from static lists + DB entries)
- **Process dropdown** — 16 processing methods (Washed, Natural, Honey variants, Anaerobic, Carbonic Maceration, etc.)
- **Bag inventory** — track weight (default 250g), price, estimated grams remaining
- **Archive** — hide empty bags from main list, browse archived coffees
- **On-screen keyboard** — simple-keyboard with German umlauts (ä/ö/ü), special characters, single-char shift toggle
- **Dark theme** — touch-optimized UI for 800x480 DSI touchscreen

## Stack

- **Backend**: Python 3.13 / Flask
- **Database**: SQLite (WAL mode, foreign keys)
- **Frontend**: HTML/CSS/JS with simple-keyboard
- **Display**: Chromium in kiosk mode (Wayland, cache disabled)
- **Grind optimization**: numpy (quadratic regression)

## Hardware

- Raspberry Pi 4 Model B (8GB)
- Official Raspberry Pi 7" capacitive touchscreen (800x480)
- Raspberry Pi OS 64-bit (Trixie)

## Deployment

The app runs on the Pi as a systemd service (`coffee-kiosk.service`) and auto-launches Chromium in kiosk mode at login.

### Files on the Pi

```
~/coffee-app/
├── app.py                      # Flask application
├── coffee.db                   # SQLite database (auto-created)
├── coffee-kiosk.service        # systemd unit file
├── restart-ui.sh               # Helper: restart Flask + Chromium
├── static/
│   ├── style.css               # Dark theme, touch-optimized
│   ├── keyboard.js             # Virtual keyboard (simple-keyboard wrapper)
│   ├── autocomplete.js         # Inline chip autocomplete
│   ├── tastingnotes.js         # Tasting note chip input + emoji lookup
│   ├── varieties.json          # ~100 coffee cultivar names
│   ├── simple-keyboard.min.js  # simple-keyboard library
│   └── simple-keyboard.css     # simple-keyboard styles
└── templates/
    ├── step1_coffee.html       # Coffee selection / creation
    ├── step2_sample.html       # Brew sample logging + grind suggestion
    ├── step3_evaluate.html     # Shot evaluation with diagnostics
    ├── edit_coffee.html        # Edit coffee details
    └── settings_notes.html     # Tasting note label management
```

### Deploy from dev machine

Configure `deploy.conf` (not checked in) with your Pi credentials:
```
PI_USER=youruser
PI_HOST=192.168.x.x
PI_APP_DIR=/home/youruser/coffee-app
```

```bash
# Source config and deploy
source deploy.conf
scp -r coffee-app/* $PI_USER@$PI_HOST:$PI_APP_DIR/
ssh $PI_USER@$PI_HOST "bash $PI_APP_DIR/restart-ui.sh"
```

### Service management

```bash
source deploy.conf
ssh $PI_USER@$PI_HOST
sudo systemctl status coffee-kiosk.service
sudo systemctl restart coffee-kiosk.service
journalctl -u coffee-kiosk.service -f
```

## API

| Endpoint | Description |
|----------|-------------|
| `GET /api/coffees` | All coffees as JSON |
| `GET /api/samples` | All samples with evaluations as JSON |
| `GET /api/autocomplete` | Unique values per field for autocomplete |
| `GET /api/custom-tasting-notes` | Custom tasting note labels |

## Database Schema

### coffees
| Column | Type | Description |
|--------|------|-------------|
| roaster | TEXT | Roasting company |
| origin_country | TEXT | Country of origin |
| origin_city | TEXT | City or region |
| origin_producer | TEXT | Farm or cooperative |
| variety | TEXT | Coffee variety (e.g. Heirloom, SL28) |
| process | TEXT | Processing method (dropdown: 16 options) |
| tasting_notes | TEXT | Comma-separated tasting notes with emoji support |
| label | TEXT | Display label (auto: roaster - variety - process) |
| roast_date | TEXT | Date of roast |
| best_after_days | INTEGER | Days before coffee is ready (default 7) |
| consume_within_days | INTEGER | Days before coffee goes stale (default 50) |
| bag_weight_g | REAL | Bag weight in grams (default 250) |
| bag_price | REAL | Price in EUR |
| default_grams_in | REAL | Roaster's recommended dose |
| default_grams_out | REAL | Roaster's recommended yield |
| default_brew_time_sec | INTEGER | Roaster's recommended brew time |
| archived | INTEGER | 0 = active, 1 = archived (empty bag) |

### samples
| Column | Type | Description |
|--------|------|-------------|
| coffee_id | INTEGER | FK to coffees |
| grind_size | REAL | Grinder setting |
| grams_in | REAL | Dose weight |
| grams_out | REAL | Yield weight |
| brew_time_sec | INTEGER | Total brew time in seconds |
| ratio | REAL | Auto-calculated (out / in) |
| notes | TEXT | Barista's notes |

### evaluations
| Column | Type | Description |
|--------|------|-------------|
| sample_id | INTEGER | FK to samples (unique) |
| aroma | INTEGER | 1–5 (none → complex) |
| acidity | INTEGER | 1–5 (flat → bright) |
| sweetness | INTEGER | 1–5 (absent → rich) |
| body | INTEGER | 1–5 (thin → full) |
| balance | INTEGER | 1–5 (poor → integrated) |
| overall | INTEGER | 1–5 (bad → excellent) |
| representative | INTEGER | 1 = counts toward coffee rating |

### custom_tasting_notes
| Column | Type | Description |
|--------|------|-------------|
| name | TEXT | Note name (unique) |
| emoji | TEXT | Emoji for display |

## Freshness Model

Based on SCA research. Configurable per coffee via best_after_days and consume_within_days.

| Stage | Default Days | Description | Badge Color |
|-------|-------------|-------------|-------------|
| Degassing | 0–2 | High CO2, shots sour/unstable | Red |
| Resting | 3–7 | CO2 releasing, almost ready | Amber |
| Peak | 7–18 | Origin character vibrant, crema rich | Green |
| Good | 18–32 | Some volatiles fading, still pleasant | Blue |
| Fading | 32–50 | Noticeably flat, papery notes | Tan |
| Stale | 50+ | Cardboard/musty, not recommended | Red |

### Roast-level presets
- **Light roast**: best_after=12, consume_within=60
- **Medium roast**: best_after=7, consume_within=50
- **Dark roast**: best_after=4, consume_within=35

## Evaluation & Rating

### Diagnostics
| Pattern | Diagnosis | Suggestion |
|---------|-----------|------------|
| High acidity + low sweetness + thin body | Under-extracted | Grind finer |
| High acidity + low sweetness | Slightly under-extracted | Grind a touch finer |
| Low acidity + low sweetness | Over-extracted | Grind coarser |
| Thin body + decent sweetness | Low extraction | Increase dose or grind finer |
| High balance + high overall | Balanced shot | Save as reference recipe |

### Coffee Rating Tiers
Computed from representative shots only (average of 5 taste dimensions).

| Average Score | Tier | Description |
|--------------|------|-------------|
| >= 4.5 | Outstanding | Exceptional |
| >= 3.8 | Excellent | Distinct, expressive |
| >= 3.0 | Very Good | Clean, pleasant |
| >= 2.2 | Good | Drinkable |
| < 2.2 | Below Average | Needs work |

### Grind Suggestion
Quadratic regression on overall score vs grind size. Requires 3+ evaluated shots. Shows confidence level (low/medium/high) based on sample count.

## Processing Methods

Dropdown selection with 16 options:
Washed, Natural, Honey, Black Honey, Red Honey, Yellow Honey, White Honey, Anaerobic, Anaerobic Natural, Anaerobic Washed, Carbonic Maceration, Wet Hulled, Semi-Washed, Double Washed, Lactic Process, Swiss Water Decaf

## Known Chromium/Wayland Issues

- `position: fixed` elements toggled via `display: none/block` won't repaint — use `:empty` collapse or `opacity` instead
- Chromium cache is aggressive in kiosk mode — disabled via `--disk-cache-size=1 --aggressive-cache-discard`
- Static asset versioning uses Flask startup timestamp (`?v={{ v }}`)

## Roadmap

- [x] Grind size suggestions based on history
- [ ] Lookup: search and filter past samples across all coffees
- [ ] Export: CSV/JSON data export
- [ ] Charts: trend visualization per coffee
- [ ] Backup: automated DB backup
