# Feature Roadmap — Post beta-v0.5

Researched 2026-04-03. Based on Perplexity research of Beanconqueror, Decent, Baristapp, and home barista needs.

## Tier 1: High Impact (next sprint)

### Shot Comparison & Trend Charts
- Side-by-side shot cards (same coffee, different grind)
- Line graphs: score trends over time per coffee
- "Best performing grind" summary
- Dose vs yield vs score correlation overlay
- **Why**: Users need to *see* patterns, not just numbers

### Recipe Presets per Coffee
- Save "dialed-in" settings as named recipe (grind + dose + yield + time)
- Quick-switch presets when returning to a known coffee
- Low effort, high value — reduces waste

### Extraction Yield Calculator
- Auto-calculate extraction % from dose + yield
- Visual guide: aim for 18-22%
- Link to taste diagnostics: "Sour + low extraction → grind finer"

## Tier 2: Medium Impact

### Ambient Always-On Dashboard (RPi-specific)
- Idle screen: last 3 days' shots, freshness countdown, weekly summary
- "Pulled 12 shots this week, avg 4.1, best: Ethiopian at grind 6"
- Leverages the always-on touchscreen form factor

### Simple ML Grind Optimizer
- Expand quadratic regression: predict optimal dose, flag anomalies
- Cross-coffee patterns: "Washed coffees peak at grind 6-7"
- ~30-50 shots per coffee sufficient, no external ML needed

### Bluetooth Scale Integration
- Acaia scales via `pyacaia` Python library (most mature RPi path)
- Felicita Arc or Skale II as alternatives
- Automatic dose/yield logging, live weight tracking
- Only if manual entry feels like friction

## Tier 3: Nice to Have

- Coffee journal / sharing
- Cost-per-cup tracking (bag_price / shots_from_bag)
- Temperature sensor integration (PID water heater)
- CSV/JSON data export
- DB backup to cloud/USB

## Competitive Advantages to Lean Into

1. **Dedicated hardware** — always-on display can show ambient info phone apps can't
2. **Simplicity** — focused on 1-3 shots/day, not $3k machine workflows
3. **Freshness model** — 6-stage decay tracking is rare among competitors
4. **Grind optimization** — quadratic regression is more sophisticated than linear logging
