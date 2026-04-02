# Coffee Sampler — Feature Guide

## Application Flow

```
┌──────────────────────────────────────────────────┐
│              SELECT A COFFEE                      │
│                                                   │
│  ┌──────────────────────────────────────────────┐ │
│  │  + New Coffee                                │ │
│  └──────────────────────────────────────────────┘ │
│                                                   │
│  ┌──────────────────────────────────────────────┐ │
│  │  Kilimbi Honey          [PEAK] [3.8/5]       │ │
│  │  Roaster · Kenya · Honey · Roasted 2026-03-25│ │
│  │  Excellent — Sweet, Full-bodied (2 rep.)     │ │
│  │  ~180g left of 250g    🍯 honey  🍫 cacao   │ │
│  └──────────────────────────────────────────────┘ │
│                                                   │
│  ┌──────────────────────────────────────────────┐ │
│  │  Rise Up                [GOOD]               │ │
│  │  ...                                         │ │
│  └──────────────────────────────────────────────┘ │
│                                                   │
│            Show archived coffees                  │
│                 Quit App                           │
└──────────────────────────────────────────────────┘
         │                           │
         ▼ (tap card)                ▼ (tap pencil)
┌─────────────────────┐    ┌─────────────────────┐
│   BREW SAMPLE       │    │   EDIT COFFEE        │
│   (Step 2)          │    │                      │
│                      │    │   All fields editable│
│   Grind suggestion   │    │   Archive button     │
│   Pre-filled recipe  │    │   Delete button      │
│   Brew history table │    └─────────────────────┘
└─────────┬───────────┘
          │ (save sample)
          ▼
┌─────────────────────┐
│   EVALUATE SHOT     │
│   (Step 3)          │
│                      │
│   6 dimensions 1-5   │
│   Representative ☑   │
│   Freshness badge    │
│   Diagnostic tips    │
└─────────────────────┘
```

## 1. Coffee Management

### Creating a Coffee

Fields (all optional except label):

| Field | Description | Autocomplete |
|-------|-------------|-------------|
| Roaster | Company name | From DB entries |
| Country | Country of origin | 46 countries + DB |
| City/Region | Growing region | From DB entries |
| Producer | Farm or cooperative | From DB entries |
| Variety | Coffee cultivar | ~100 varieties + DB |
| Process | Processing method | Dropdown (16 options) |
| Tasting Notes | Seller's flavor notes | Emoji chip input |
| Label | Display name | Auto: roaster - variety - process |
| Roast Date | When roasted | Date picker |
| Bag (g) | Bag weight | Default 250 |
| Price (€) | Bag cost | — |
| Dose In (g) | Roaster's recommended dose | — |
| Yield Out (g) | Roaster's recommended yield | — |
| Brew Time (sec) | Roaster's recommended time | — |
| Best After (days) | Rest period | Default 7 |
| Use Within (days) | Shelf life | Default 50 |

### Processing Methods (Dropdown)

| Method | Description |
|--------|-------------|
| Washed | Cherry skin removed, fermented in water |
| Natural | Dried whole cherry |
| Honey | Skin removed, mucilage left |
| Black/Red/Yellow/White Honey | Varying mucilage amounts |
| Anaerobic | Sealed oxygen-free fermentation |
| Anaerobic Natural/Washed | Anaerobic + base method |
| Carbonic Maceration | CO2-flooded fermentation |
| Wet Hulled | Indonesian Giling Basah |
| Semi-Washed | Partial mucilage removal |
| Double Washed | Extended wash cycles |
| Lactic Process | Bacteria-specific fermentation |
| Swiss Water Decaf | Chemical-free decaffeination |

### Bag Inventory

The app tracks remaining coffee:

```
Remaining = bag_weight_g - SUM(grams_in from all samples)
```

Displayed on coffee cards: `~180g left of 250g`

### Archiving

When a bag is empty, archive it from the edit page. Archived coffees are hidden from the main list but accessible via "Show archived coffees" at the bottom.

## 2. Freshness Tracking

Based on SCA research on coffee degradation in sealed bags, cool and dark storage.

### Stages

```
Day:  0   2   3       7          18         32         50
      |---|---|-------|----------|----------|----------|------→
      DEG  REST       PEAK       GOOD       FADING     STALE
      🔴   🟡         🟢          🔵          🟤         🔴
```

| Stage | Days (medium roast) | What's Happening |
|-------|-------------------|-----------------|
| **Degassing** | 0–2 | High CO2. Shots sour, unstable, erratic crema |
| **Resting** | 3–7 | CO2 releasing. Improving daily, not yet optimal |
| **Peak** | 7–18 | Origin character vibrant. Crema rich. Best window |
| **Good** | 18–32 | Volatile aromatics fading. Still very pleasant |
| **Fading** | 32–50 | Noticeably flat. Papery notes emerging |
| **Stale** | 50+ | Cardboard/musty. Crema absent. Not recommended |

### Roast-Level Presets

| Roast | Best After | Use Within |
|-------|-----------|-----------|
| Light | 12 days | 60 days |
| Medium | 7 days | 50 days |
| Dark | 4 days | 35 days |

## 3. Brew Sample Logging

### Pre-filled Recipe

If the coffee has roaster's recipe defaults set, the sample form is pre-filled:
- **In (g)** — from `default_grams_in`
- **Out (g)** — from `default_grams_out`
- **Time (sec)** — from `default_brew_time_sec`

Only the **grind size** needs to be entered manually (grinder-specific).

### Grind Size Suggestion

Uses quadratic regression on past evaluated shots:

```
score = a · grind² + b · grind + c
optimal_grind = -b / (2a)
```

| Data Available | Behavior |
|---------------|----------|
| 0 shots | No suggestion |
| 1–2 evaluated shots | Shows best-scoring grind |
| 3+ evaluated shots | Fits quadratic curve, suggests optimal |
| 6+ evaluated shots | High confidence suggestion |

#### Example

```
Shots for "Kilimbi Honey":
  Grind 12.0 → Overall 2/5 (too coarse, sour)
  Grind 14.0 → Overall 4/5 (good)
  Grind 15.0 → Overall 5/5 (excellent)  ← peak
  Grind 16.0 → Overall 4/5 (slightly bitter)
  Grind 18.0 → Overall 2/5 (over-extracted)

Quadratic fit finds peak at grind ~15.1
→ "Suggested grind: 15.1 (predicted 4.8/5 from 5 shots)"
```

### Brew History Table

| Date | Grind | In | Out | Ratio | Time | Score |
|------|-------|-----|-----|-------|------|-------|
| 2026-04-03 | 15.0 | 18g | 36g | 1:2.0 | 28s | 5/5 |
| 2026-04-02 | 14.0 | 18g | 38g | 1:2.1 | 30s | 4/5 |
| 2026-04-01 | 12.0 | 18g | 42g | 1:2.3 | 22s | 2/5 |

Tap score to re-evaluate. Tap "rate" to evaluate unrated shots.

## 4. Shot Evaluation

### Dimensions (1–5 Scale)

| Dimension | 1 | 2 | 3 | 4 | 5 |
|-----------|---|---|---|---|---|
| **Aroma** | None | Subtle | Moderate | Prominent | Complex |
| **Acidity** | Flat | Soft | Balanced | Bright | Vibrant |
| **Sweetness** | Absent | Low | Balanced | Sweet | Very sweet |
| **Body** | Thin | Delicate | Medium | Creamy | Heavy |
| **Balance** | Poor | Unbalanced | Balanced | Excellent | Integrated |
| **Overall** | Bad | Below avg | Good | Very good | Excellent |

### Representative Flag

Check "Representative shot for this coffee" on shots that reflect the coffee's true character (not dialing-in experiments). Only representative shots count toward the coffee's aggregate rating.

### Diagnostic Feedback

Automatic tips based on score patterns:

| Scores | Diagnosis | Action |
|--------|-----------|--------|
| Acidity ≥4, Sweetness ≤2, Body ≤2 | Under-extracted | Grind finer or extend brew time |
| Acidity ≥4, Sweetness ≤2 | Slightly under-extracted | Grind a touch finer |
| Acidity ≤2, Sweetness ≤2 | Over-extracted | Grind coarser or shorter brew |
| Body ≤2, Sweetness ≥3 | Thin body | Increase dose or grind finer |
| Balance ≥4, Overall ≥4 | Balanced shot | Save as reference recipe |
| Overall ≥4 (no other issues) | Solid shot | Minor tweaks possible |

### Example Diagnostic

```
Shot: Grind 12.0, 18g in → 42g out, 22s
Scores: Aroma 3, Acidity 5, Sweetness 1, Body 2, Balance 1, Overall 2

Diagnostic: "Likely under-extracted. Try grinding finer or extending brew time."
```

## 5. Coffee Rating

Computed from **representative shots only**.

### Calculation

```
avg_taste = mean(aroma, acidity, sweetness, body, balance)   # excludes "overall"
```

### Tier Labels

| Average | Tier | Badge Color |
|---------|------|-------------|
| ≥ 4.5 | Outstanding | Bright green |
| ≥ 3.8 | Excellent | Blue |
| ≥ 3.0 | Very Good | Muted green |
| ≥ 2.2 | Good | Yellow |
| < 2.2 | Below Average | Red |

### Flavor Profile Descriptors

Auto-generated from dimension averages:

| Condition | Descriptor |
|-----------|-----------|
| Acidity ≥ 3.5 | "Bright" |
| Acidity ≤ 2 | "Mellow" |
| Sweetness ≥ 3.5 | "Sweet" |
| Body ≥ 3.5 | "Full-bodied" |
| Body ≤ 2 | "Light" |
| Balance ≥ 4 | "Well-balanced" |
| Aroma ≥ 4 | "Aromatic" |

### Example Rating

```
Coffee: "Kilimbi Honey" (2 representative shots)

Shot 1: Aroma 4, Acidity 3, Sweetness 5, Body 4, Balance 5
Shot 2: Aroma 4, Acidity 2, Sweetness 4, Body 4, Balance 4

Averages: Aroma 4.0, Acidity 2.5, Sweetness 4.5, Body 4.0, Balance 4.5
avg_taste = (4.0 + 2.5 + 4.5 + 4.0 + 4.5) / 5 = 3.9

Tier: "Excellent"
Profile: "Sweet, Full-bodied, Well-balanced, Aromatic"
Display: "Excellent — Sweet, Full-bodied, Well-balanced, Aromatic (2 rep. shots)"
```

## 6. Tasting Notes System

### Input (Chip Component)

- Tap field → see common suggestions
- Type to filter (e.g. "ch" → cherry, chocolate, cinnamon)
- Tap a chip to add
- Tap × to remove
- Stored as comma-separated text: `"dried apricot, cacao nibs, honey"`

### Emoji Mapping

~90 built-in note→emoji mappings. Displayed on:
- Coffee cards (overview page, bottom right)
- Coffee detail strip (sample page)
- Chip input component

### Settings (Gear Icon)

- **Add custom labels** with emoji picker (searchable grid)
- **Edit built-in labels** — change emoji, reset to default
- **Edit custom labels** — change name + emoji, or delete
- Duplicate prevention (case-insensitive)

## 7. Autocomplete

Inline suggestion chips appear below fields as you type. No floating/positioned elements (Wayland compatibility).

### Data Sources

| Field | Static List | DB Entries |
|-------|------------|-----------|
| Roaster | — | From existing coffees |
| Country | 46 countries | + DB entries |
| City/Region | — | From existing coffees |
| Producer | — | From existing coffees |
| Variety | ~100 cultivars | + DB entries |

Lists grow automatically as you add more coffees.

## 8. Database Backups

- **Automatic daily backup** on each Flask startup
- Stored in `~/coffee-app/backups/coffee-YYYY-MM-DD.db`
- **Auto-pruned** after 60 days
- One backup per day (skips if today's backup exists)

## 9. Undo Support

After deleting a coffee or sample, an **undo banner** appears:

```
┌──────────────────────────────────────────┐
│ Deleted coffee: Kilimbi Honey    [Undo]  │
└──────────────────────────────────────────┘
```

Tap "Undo" to restore the deleted item with all its samples and evaluations. Persists until the next delete or session end.

## 10. Virtual Keyboard

Custom on-screen keyboard (simple-keyboard) optimized for the 800x480 touchscreen:

- **Default layout**: QWERTY + ä, ö, ü on right side
- **Shift**: Single-character toggle (auto-returns to lowercase)
- **123**: Numbers and punctuation
- **àü**: Full accented characters (ß, à, á, â, ã, å, æ, è, é, etc.)
- **Done**: Dismiss keyboard

## 11. Kiosk Mode

- Chromium launches in kiosk mode at boot (fullscreen, no browser chrome)
- **Quit App** button (home page bottom) kills Chromium, returns to desktop
- **Desktop icon** to relaunch the kiosk on demand
- **Autologin** enabled (no password on boot)
- Cache disabled for reliable deploys (`--disk-cache-size=1`)
