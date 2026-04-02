# Coffee Sampler

A touchscreen coffee sampling app for Raspberry Pi with the official 7" display.

## Overview

Track espresso shots and dial in your grind. Three-step workflow:

1. **Select or define a coffee** — roaster, origin, variety, process, tasting notes, roast date
2. **Log a brew sample** — grind size, dose in/out, brew time
3. **Evaluate the shot** — score aroma, acidity, sweetness, body, balance (1–5 scale) with automatic diagnostic feedback

## Stack

- **Backend**: Python / Flask
- **Database**: SQLite (WAL mode)
- **Frontend**: HTML/CSS with on-screen keyboard (simple-keyboard)
- **Display**: Chromium in kiosk mode on 800x480 DSI touchscreen

## Hardware

- Raspberry Pi 4 Model B (8GB)
- Official Raspberry Pi 7" capacitive touchscreen
- Raspberry Pi OS 64-bit (Bookworm/Trixie)

## Deployment

The app runs on the Pi as a systemd service (`coffee-kiosk.service`) and auto-launches Chromium in kiosk mode at login.

### Files on the Pi

```
~/coffee-app/
├── app.py                  # Flask application
├── coffee.db               # SQLite database (auto-created)
├── coffee-kiosk.service    # systemd unit file
├── static/
│   ├── style.css           # Dark theme, touch-optimized
│   ├── keyboard.js         # On-screen keyboard integration
│   ├── simple-keyboard.min.js
│   └── simple-keyboard.css
└── templates/
    ├── step1_coffee.html   # Coffee selection / creation
    ├── step2_sample.html   # Brew sample logging
    └── step3_evaluate.html # Shot evaluation with diagnostics
```

### Deploy from dev machine

```bash
scp -r coffee-app/* DEPLOY_USER@PI_HOST_IP:~/coffee-app/
ssh DEPLOY_USER@PI_HOST_IP "sudo systemctl restart coffee-kiosk.service"
```

### Service management

```bash
ssh DEPLOY_USER@PI_HOST_IP
sudo systemctl status coffee-kiosk.service
sudo systemctl restart coffee-kiosk.service
journalctl -u coffee-kiosk.service -f
```

## API

- `GET /api/coffees` — all coffees as JSON
- `GET /api/samples` — all samples with evaluations as JSON

## Database Schema

### coffees
| Column | Type | Description |
|--------|------|-------------|
| roaster | TEXT | Roasting company |
| origin_country | TEXT | Country of origin |
| origin_city | TEXT | City or region |
| origin_producer | TEXT | Farm or cooperative |
| variety | TEXT | Coffee variety (e.g. Heirloom, SL28) |
| process | TEXT | Processing method (washed, natural, honey) |
| tasting_notes | TEXT | Seller's tasting notes |
| label | TEXT | Display label (auto-generated if blank) |
| roast_date | TEXT | Date of roast |

### samples
| Column | Type | Description |
|--------|------|-------------|
| coffee_id | INTEGER | FK to coffees |
| grind_size | REAL | Grinder setting |
| grams_in | REAL | Dose weight |
| grams_out | REAL | Yield weight |
| brew_time_sec | INTEGER | Total brew time |
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

## Evaluation Diagnostics

After scoring a shot, the app provides actionable feedback:

| Pattern | Diagnosis | Suggestion |
|---------|-----------|------------|
| High acidity + low sweetness + thin body | Under-extracted | Grind finer |
| High acidity + low sweetness | Slightly under-extracted | Grind a touch finer |
| Low acidity + low sweetness | Over-extracted | Grind coarser |
| Thin body + decent sweetness | Low extraction | Increase dose or grind finer |
| High balance + high overall | Balanced shot | Save as reference recipe |

## Roadmap

- [ ] Lookup: search and filter past samples
- [ ] Predictions: suggest grind settings based on history
- [ ] Export: CSV/JSON data export
- [ ] Charts: trend visualization per coffee
