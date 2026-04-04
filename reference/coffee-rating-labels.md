# Coffee Rating Labels & Flavor Profiles

Sources: SCA scoring standards, Perplexity research.

## SCA Score Tiers (0-100 Scale)

| Score | Label | Definition |
|-------|-------|-----------|
| 90-100 | Outstanding | Rare, exceptional clarity, complexity, sweetness |
| 85-89.99 | Excellent | Distinct, expressive; typical of specialty roasters |
| 80-84.99 | Very Good | Entry-level specialty; clean, sweet, minimal defects |
| 70-79.99 | Good | Drinkable, pleasant; borderline specialty |
| Below 70 | Below Average | Commercial-grade; defects or flat |

## App Implementation (1-5 scale)

### Quality Score (for tier)

Weighted combination of universal quality indicators + user taste preferences:

**Always included (fixed weights):**
- Balance (weight 1)
- Overall score (weight 2)

**User-configurable (Settings → Taste Profile):**
- Sweetness, Acidity, Body, Aroma — each set on a 1-5 preference scale
- Preference maps to weight: `w = (preference - 3) / 2` → range -1 to +1
  - 5 = "I love this" → weight +1 (high scores boost quality)
  - 3 = "Neutral" → weight 0 (ignored, default)
  - 1 = "I dislike this" → weight -1 (high scores hurt quality)

**Formula:**
```
quality = (balance + 2×overall + w_sweet×sweetness + w_acid×acidity + w_body×body + w_aroma×aroma)
          / (3 + |w_sweet| + |w_acid| + |w_body| + |w_aroma|)
```

### Tier Mapping (quality score)

| Quality | Tier | Color |
|---------|------|-------|
| >= 4.5 | Outstanding | Bright green |
| >= 3.8 | Excellent | Blue |
| >= 3.0 | Very Good | Muted green |
| >= 2.2 | Good | Yellow |
| < 2.2 | Below Average | Red |

### Flavor Profile Descriptors

Flavor profile describes the coffee's character, separate from quality tier.
Uses acidity, body, and aroma only (not quality indicators):

**Acidity**
- >= 3.5: "Bright"
- <= 2: "Mellow"

**Body**
- >= 3.5: "Full-bodied"
- <= 2: "Light"

**Aroma**
- >= 4: "Aromatic"

Example output: "Bright, Full-bodied, Aromatic"

### Extended Descriptors (from SCA research)

| Dimension | Score 1 | Score 2 | Score 3 | Score 4 | Score 5 |
|-----------|---------|---------|---------|---------|---------|
| Aroma | Muted | Subtle | Moderate | Prominent | Intense, complex |
| Acidity | Flat, dull | Soft, mild | Balanced, crisp | Bright, lively | Vibrant, sharp |
| Sweetness | Bitter, dry | Low | Balanced | Sweet, honey-like | Very sweet |
| Body | Tea-like | Thin | Medium | Creamy, syrupy | Heavy, thick |
| Balance | Disjointed | Unbalanced | Well-balanced | Excellent | Perfectly integrated |

## Notes

- Only representative shots count for the aggregate rating
- Freshness at time of evaluation is tracked as context
- SCA conversion possible: `(quality - 1) * 25` maps 1-5 to 0-100
- Quality score is used for: coffee card badges, stats page tier, insights rankings, value metric
- Taste preferences stored in `app_settings` table as JSON (key: `taste_preferences`)
- Default preferences are all 3 (neutral) — quality = (balance + 2×overall) / 3
