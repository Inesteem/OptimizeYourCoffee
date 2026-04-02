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

Average of 5 taste dimensions (aroma, acidity, sweetness, body, balance), excluding
"overall" which is the user's own summary.

### Tier Mapping (1-5 average)

| Average | Tier | Color |
|---------|------|-------|
| >= 4.5 | Outstanding | Bright green |
| >= 3.8 | Excellent | Blue |
| >= 3.0 | Very Good | Muted green |
| >= 2.2 | Good | Yellow |
| < 2.2 | Below Average | Red |

### Flavor Profile Descriptors

Per-dimension descriptors based on score:

**Acidity**
- >= 3.5: "Bright"
- <= 2: "Mellow"

**Sweetness**
- >= 3.5: "Sweet"

**Body**
- >= 3.5: "Full-bodied"
- <= 2: "Light"

**Balance**
- >= 4: "Well-balanced"

**Aroma**
- >= 4: "Aromatic"

Example output: "Bright, Sweet, Full-bodied, Well-balanced"

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
- SCA conversion possible: `(rating - 1) * 25` maps 1-5 to 0-100
- Equal weighting works well for home use; SCA pros sometimes weight overall higher
