# Espresso Evaluation Framework

Sources: SCA Cupping Form, WBC Scoresheet, Baristapp, Smart Espresso Profiler, home barista consensus.

## Professional Standards

### SCA Cupping Form
- 10 attributes: aroma, flavor, acidity, body, balance, sweetness, uniformity, clean cup, aftertaste
- Scored on 6.0-10.0 scale
- Too complex for home use

### WBC Scoresheet
- Heavily weights taste balance and tactile experience
- Scored 0-6 per attribute
- Includes crema evaluation (gate criteria)

## Recommended Dimensions for Home Espresso (1-5 scale)

| Dimension | Scale | Diagnostic Value |
|-----------|-------|-----------------|
| **Aroma** | None (1) to Complex (5) | Freshness/roast quality indicator |
| **Acidity** | Flat (1) to Bright (5) | High = under-extracted (grind finer) |
| **Sweetness** | Absent (1) to Rich (5) | Low = extraction problem |
| **Body** | Thin (1) to Full (5) | Thin = grind too coarse |
| **Balance** | Poor (1) to Integrated (5) | Overall harmony of flavors |
| **Overall** | Bad (1) to Excellent (5) | "Would I make this again?" |

## Diagnostic Patterns

| Pattern | Diagnosis | Suggestion |
|---------|-----------|------------|
| High acidity + low sweetness + thin body | Under-extracted | Grind finer or extend brew time |
| High acidity + low sweetness | Slightly under-extracted | Grind a touch finer |
| Low acidity + low sweetness | Over-extracted | Grind coarser or shorter brew |
| Thin body + decent sweetness | Low extraction | Increase dose or grind finer |
| High balance + high overall | Balanced shot | Save as reference recipe |

## What Was Excluded (and Why)

- **Crema**: Visual/cosmetic — doesn't reliably indicate taste quality
- **Flavor wheel descriptors**: Too slow for touchscreen entry
- **Defects**: Binary pass/fail, not a scale
- **Aftertaste**: Covered implicitly by balance and overall
- **Uniformity/Clean cup**: Relevant for cupping multiple cups, not single espresso

## Scoring Approach

- **1-5 discrete numeric** (not sliders, not 1-10)
- Simpler, more consistent across sessions
- Easier to compare trends over time
- Better for touchscreen UX
- All existing apps (Baristapp, Beanlog, etc.) use discrete points

## Additional Evaluation Fields (implemented)

### Sensory Descriptors (3 sections)
- **Grind Smell** (19 chips): captured during sample input, before brewing
- **Brew Smell** (18 chips): what the brewed espresso smells like
- **Taste Notes** (30 chips): includes diagnostic negatives (Sour, Bitter, Burned, etc.)

### Other Fields
- **Grind Aroma** (1-5): intensity score, pre-filled from last eval of same coffee
- **Preheat**: portafilter, cup, machine checkboxes (default checked)
- **With Milk**: flags shots consumed with milk (affects perception)
- **Notes**: free-text field
- **Representative**: checked by default, uncheck for experimental shots

## UX Notes

- Radio buttons are most touch-friendly
- Stack dimensions vertically
- ~30 seconds to complete full evaluation with descriptors
- Show diagnostic feedback immediately after scoring
- Diagnostics use taste descriptors even with 0 prior data
