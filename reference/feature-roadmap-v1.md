# Feature Roadmap — Post beta-v0.5

Researched 2026-04-03. Updated 2026-04-03.

## Tier 1: High Impact — DONE

### Shot Comparison & Trend Charts — DONE
- [x] Grind vs Score scatter chart
- [x] Score + Grind timeline (dual-axis)
- [x] Flavor radar chart (5 dimensions)
- [x] Cross-coffee bar chart comparison
- [x] Key stats summary (shots, avg score, best grind, ratio)

### Extraction Diagnostics — DONE
- [x] Taste descriptor-based recommendations (sour→finer, bitter→coarser)
- [x] Brew time diagnostic (fast/slow confirmation)
- [x] Output deviation (ratio-based target, ±2g/5g/10g thresholds)
- [x] Channeling detection (sour+bitter simultaneously)
- [x] 3 severity levels (1 step, 1-2 steps, 2-3 steps)
- [x] Real-time output deviation display on sample form

### Recipe Presets per Coffee — PARTIAL
- [x] Roaster's default recipe (dose, yield, time) stored per coffee
- [x] Pre-fills sample form
- [ ] Named presets (save "dialed-in" grind as named recipe)
- [ ] Quick-switch between presets

## Tier 2: Medium Impact — IN PROGRESS

### Grind Optimizer — DONE
- [x] Quadratic regression on scores
- [x] Confidence levels (low/medium/high)
- [x] Shown on sample page

### Ambient Always-On Dashboard
- [ ] Idle screen with last shots, freshness, weekly summary

### Bluetooth Scale Integration
- [ ] Acaia scales via pyacaia
- [ ] Auto dose/yield logging

## Tier 3: Nice to Have

- [ ] Named recipe presets with quick-switch
- [ ] Coffee journal / sharing
- [ ] Cost-per-cup tracking
- [ ] CSV/JSON data export
- [ ] DB backup to cloud/USB
- [ ] Cross-coffee pattern insights ("Washed coffees peak at grind X")

## Competitive Advantages

1. **Dedicated hardware** — always-on display for ambient info
2. **Simplicity** — focused on 1-3 shots/day
3. **Freshness model** — 6-stage decay tracking
4. **Grind optimization** — quadratic regression
5. **Taste-based diagnostics** — zero-shot recommendations from descriptors
