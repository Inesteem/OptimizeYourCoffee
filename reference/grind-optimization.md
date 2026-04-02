# Grind Size Optimization

Sources: Perplexity research, espresso extraction science, quadratic regression approach.

## Core Relationship

- Finer grind → slower flow → less output (for same brew time)
- Grind response is smooth — no sharp discontinuities between settings
- There's a "sweet spot" where extraction balance (acidity vs bitterness) is optimal

## Approach: Quadratic Regression on Overall Score

Fit a quadratic model to evaluation scores vs grind size:
```
score = a + b·grind_step + c·grind_step²
```

Peak of parabola: `optimal_step = -b / (2c)`

### Why Quadratic Works
- Flexible enough for 1D nonlinear behavior without overfitting
- Handles the typical "too sour ← sweet spot → too bitter" curve
- Works with as few as 4-6 data points
- Interpretable: shows response slope to grind changes

### Minimum Data Requirements
- **< 3 shots**: Not enough data, show weighted average of best shots
- **3+ shots with evaluations**: Can fit quadratic and suggest optimal
- **5+ shots**: High confidence suggestion

### Optimization Target
- Primary: maximize overall evaluation score
- Penalty for shots far from target brew time (if set)
- Only consider shots with evaluations (ignore unevaluated shots)

### Edge Cases
- If quadratic coefficient `c` is positive (U-shape instead of hill), the model found a minimum not maximum — fall back to best-scoring shot's grind
- If optimal grind is outside observed range, suggest extending range (try finer/coarser)
- If all scores are similar, current approach is working — no strong suggestion

## Implementation
Uses numpy.polyfit for least-squares quadratic regression. Shown as a suggestion banner on the sample logging page with confidence indication.
