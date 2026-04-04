# Grind Size Optimization

Sources: Perplexity research, Gemini review, espresso extraction science.

## Core Relationship

- Finer grind → slower flow → less output (for same brew time)
- Grind response is smooth — no sharp discontinuities between settings
- There's a "sweet spot" where extraction balance (acidity vs bitterness) is optimal

## Assumptions

All algorithms optimize **grind size as a single variable**. They assume you keep your dose (input grams) roughly the same and either fix brew time or output grams between shots. If you change multiple brew parameters at once, suggestions become less reliable. Use "Same recipe only" filtering to exclude shots from different setups.

## Three Available Algorithms

Users can choose between algorithms in Settings → Grind Optimizer.

### 1. Best Shots (Weighted Centroid) — Default

Averages grind settings from your highest-scoring shots, weighted by recency.

**How it works:**
- Rank all evaluated shots by `score^power * exp(-decay_rate * days_ago)`
- Take the top N shots
- Compute their weighted average grind setting

**Tunable parameters:**
- `decay_rate` (default 0.05): How fast old shots lose influence. 0 = all equal, 0.2 = only last few days matter
- `top_n` (default 3): How many top shots to average
- `score_weight_power` (default 2.0): How much higher scores dominate. At 2, a 5/5 shot outweighs a 3/5 shot by 25:9

**Minimum data:** 2 shots (below that, falls back to cross-coffee prior or best shot)

**Best for:** Everyday use, any number of shots. Adapts naturally as beans age.

### 2. Smart Curve (Bayesian Quadratic)

Fits a regularized parabola through scores to find the peak grind setting. Adds a "caution level" (L2 regularization) that prevents wild predictions with sparse data.

**How it works:**
- Weighted ridge regression: `score = a·grind² + b·grind + c` with L2 penalty
- Peak at `-b / (2a)` gives the suggested grind
- Optional recency weighting via time-decay
- Solved via Cramer's rule on 3×3 normal equations (no numpy needed)

**Tunable parameters:**
- `prior_strength` (default 1.0): Regularization strength. 0 = no safety net (same as Classic), 5+ = very conservative
- `decay_rate` (default 0.05): Recency bias (only when recency is on)
- `use_recency` (default on): Whether to weight recent shots more

**Relationship to Classic Curve:** Smart Curve with caution at 0 and recency off is identical to Classic Curve Fit.

**Minimum data:** 3 shots

**Best for:** 4-8 shots across different grind sizes.

### 3. Classic Curve Fit (Quadratic Regression)

Original algorithm. Fits a parabola via least-squares regression (numpy.polyfit). No regularization, no recency — raw mathematical fit.

**How it works:**
- Standard quadratic regression: `score = a·grind² + b·grind + c`
- Peak at `-b / (2a)` if parabola opens downward (a < 0)
- Falls back to best shot if: U-shaped curve, optimal grind >5 steps outside observed range

**No tunable parameters.** Requires numpy.

**Minimum data:** 3 shots

**Best for:** 8+ shots spread across a wide grind range in a short time.

### 4. Directed Search (Ratio Accuracy only)

Automatically used when "Ratio accuracy" is selected as the score source. Uses the monotonic relationship between grind and output — no curve fitting needed.

**How it works:**
- Grind→output is monotonic: finer grind → less output, coarser → more
- Estimates grind sensitivity (grams per step) via linear regression on (grind, output) history
- Computes exact step adjustment: `steps = (actual_out - target_out) / sensitivity`
- Falls back to default sensitivity of 2g/step with <2 shots

**No tunable parameters.** Activates automatically for ratio accuracy.

**Minimum data:** 1 shot (uses default sensitivity). 0 shots falls back to cross-coffee prior.

**Best for:** Dialing in to hit a vendor-recommended brew ratio (e.g., 18g in → 36g out).

**Note:** Assumes finer grind = lower grind number. Most common grinders follow this convention.

## Configurable Score Source

All algorithms optimize for a configurable score (Settings → Grind Optimizer → "Optimize for"):

| Source | Description |
|--------|-------------|
| Overall score | User's holistic 1-5 rating (default) |
| Taste average | Mean of aroma, acidity, sweetness, body, balance |
| Ratio accuracy | How close actual output was to target (1-5 synthetic score) |
| Single dimension | Optimize for one dimension (sweetness, acidity, etc.) |

### Ratio Accuracy Scoring

When score source is "Ratio accuracy", each shot gets a synthetic score based on deviation from the coffee's target output (`default_grams_out`):

| Deviation | Score |
|-----------|-------|
| ±1g | 5.0 |
| ±2g | 4.0 |
| ±4g | 3.0 |
| ±7g | 2.0 |
| >7g | 1.0 |

## Recipe-Matching Filter

When "Same recipe only" is enabled, algorithms only consider shots with similar brew parameters to the most recent shot:

- **Temp tolerance** (default ±2°C): Excludes shots at different temperatures
- **Dose tolerance** (default ±1g): Excludes shots with different input dose

Useful when you change brew parameters between experiments.

## Cross-Coffee Prior

When a coffee has too few shots for the algorithm to run, the system suggests a starting grind based on your other coffees on the same grinder.

**Fallback chain (most specific first):**
1. Same process + same roast level (bean color)
2. Same process only
3. Same roast level only
4. All your coffees

Requires at least 3 evaluated shots across at least 1 other coffee to fire.

## Confidence Levels

| Level | Meaning |
|-------|---------|
| Low | <3 shots, or algorithm fell back (U-shaped curve, out of range, etc.) |
| Medium | 3-5 shots, reasonable suggestion but could shift with more data |
| High | 6+ shots (4+ for ratio accuracy), stable suggestion |

## Edge Cases

- If quadratic coefficient `c` is positive (U-shape), falls back to best-scoring shot
- If optimal grind is outside observed range by >5 steps, suggests extending range
- If all scores are similar, current approach is working — no strong directional suggestion
- Unknown timestamps get minimal weight (365 days ago) rather than maximum
- NULL grind sizes are filtered out
- Algorithm parameters are clamped server-side (decay ≥ 0, top_n ≥ 1, etc.)
