# Coffee Freshness & Degradation

Sources: SCA (Specialty Coffee Association), WBC (World Barista Championship), specialty roaster consensus.

## Degassing & Rest Period

- Roasted coffee releases CO2 rapidly in the first 48 hours
- Light roasts need longer rest (up to 10-14 days for full stability)
- Dark roasts degas fastest (3-5 days)
- Brewing too early produces sour, uneven shots with explosive bubbling and thin body

## Peak Flavor Windows by Roast Level

| Roast Level | Ready to Brew | Peak Window | Still Good | Stale |
|-------------|--------------|-------------|------------|-------|
| **Light** | 7-14 days | 14-28 days | Up to 6 weeks | 60+ days |
| **Medium** | 7-10 days | 10-21 days | Up to 5 weeks | 50+ days |
| **Dark** | 3-5 days | 4-14 days | 2-3 weeks | 35+ days |

## Degradation Stages (Sealed Bag, Cool & Dark)

### Day 0-2: Degassing
- High CO2 concentration
- Extraction is uneven and unstable
- Shots taste sour, thin, with weak body
- Crema is erratic (explosive bubbling)

### Day 3-6: Resting
- CO2 releasing, flavor developing
- Not yet optimal but improving daily
- Can start dialing in towards end of this period

### Day 7-21: Peak (medium roast baseline)
- Best all-around flavor
- Origin character vibrant and complex
- Crema rich and stable
- Sweet spot for dialing in espresso

### Day 21-35: Good
- Some volatile aromatics (fruit, floral) start to fade
- Acidity becomes more muted
- Body may soften slightly
- Still very pleasant for espresso

### Day 35-50: Fading
- Noticeably flatter profile
- Papery/cardboard notes begin to emerge
- Origin character largely lost
- Body thins out
- Consider using for milk drinks

### Day 50+: Stale
- Cardboard, musty, or rancid tones
- Crema nearly absent (CO2 and oils depleted)
- Aroma dull or absent when grinding
- Taste flat, generic, hollow
- Not recommended for espresso

## Storage Conditions Impact

| Condition | Shelf Life |
|-----------|-----------|
| Sealed bag, cool & dark | 1-3 months acceptable, best in first 5 weeks |
| Opened bag, resealed loosely | 2-4 weeks before noticeable degradation |
| Opened bag, airtight container | ~40% slower degradation vs loose reseal |
| Ground coffee (opened) | 1-2 weeks; 60% of aromatics lost within 15 min of grinding |

## Key Degradation Drivers

1. **Oxidation** — primary driver, accelerated by oxygen exposure
2. **CO2 loss** — affects crema and body
3. **Moisture** — can cause mustiness
4. **Surface oil migration** — dark roasts have more exposed oil, oxidize faster

## Signs of Staleness

- Crema thin or absent
- Dull aroma when grinding
- Flat, generic taste lacking sweetness
- Papery, cardboard, or musty off-notes
- Rancid taste in severe cases

## App Implementation

### Roast-Level-Dependent Windows (auto-selected by `bean_color`)

| bean_color | Degas | best_after | Peak dur | Good dur | consume_within |
|------------|-------|------------|----------|----------|----------------|
| Light | 4d | 12 | 14 | 14 | 60 |
| Medium-Light | 3d | 10 | 13 | 14 | 55 |
| Medium | 3d | 7 | 11 | 14 | 50 |
| Medium-Dark | 2d | 5 | 9 | 12 | 42 |
| Dark | 2d | 4 | 8 | 10 | 35 |

**Default (no bean_color):** Medium-Dark (espresso roast assumption).

User-set `best_after_days` / `consume_within_days` override the roast-level defaults. Empty form fields store NULL, triggering auto-selection.

### Opened-Date Acceleration

Once a bag is opened, oxygen exposure accelerates degradation. A penalty is added to the effective `days_since_roast`:

| Days open | Penalty |
|-----------|---------|
| 0-7 | None |
| 8-14 | +5 days |
| 15-21 | +12 days |
| 22+ | +20 days |

The `days` field in the result always reflects actual days since roast; the penalty only affects stage selection. Detail text notes the acceleration (e.g., "open 10d — aging faster").
