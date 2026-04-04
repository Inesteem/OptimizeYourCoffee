# Algorithm Improvements Reference

Sources: External review by Gemini and Perplexity AI (2026-04-04), SCA research, Barista Hustle extraction science.

## Implementation Status (2026-04-04)

| Improvement | Status |
|-------------|--------|
| Grind optimizer: 3 selectable algorithms with settings UI | Done |
| Grind optimizer: configurable score source (overall, taste avg, ratio accuracy, single dimension) | Done |
| Grind optimizer: recipe-matching filter (temp/dose tolerance) | Done |
| Grind optimizer: cross-coffee prior for sparse data | Done |
| Grind optimizer: time-decay recency weighting | Done |
| Diagnostics: removed grind advice (now optimizer's job), kept observational feedback | Done |
| Diagnostics: swap output deviation above brew time in priority chain | Done |
| Grind optimizer: dedicated ratio-directed search algorithm | Done |
| Grind optimizer: auto-save settings (no save button) | Done |
| Grind optimizer: live preview via API with example scenarios | Done |
| Freshness: roast-level-dependent windows | Done |
| Freshness: opened-date acceleration | Done |
| Rating: quality-weighted tiers (incorporate overall score) | Done |
| Rating: separate quality from flavor profile dimensions | Done |
| Rating: user taste preferences (bipolar 1-5 per dimension) | Done |
| Coffee list: sorting by roasted, rating, opened (persistent + reversible) | Done |
| Insights: preference-weighted quality in all rankings | Done |
| Insights: forgiveness metric | Done |
| Insights: shot-weighted group averages | Done |
| Insights: price-per-shot value metric | Done |
| UI: origin country map icons (46 countries, SVG) | Done |
| UI: roast level guide popup (bean color reference) | Done |
| UI: 3 card designs (Modern, Showcase, Legacy) with settings toggle | Done |
| UI: cost per shot on coffee overview cards | Done |

## 1. Grind Optimizer: Weighted Centroid with Time Decay

**Replaces:** Quadratic regression (`numpy.polyfit`) on (grind, overall_score) pairs.

**New approach:** Weighted centroid of top-scoring shots with exponential time-decay.
- Select top N shots (by overall score) for the coffee
- Weight each by `exp(-λ * days_ago)` where λ controls decay speed (λ ≈ 0.05 gives ~3x weight to yesterday vs 14 days ago)
- Compute weighted average of their grind settings
- Add aging drift: suggest slightly finer as beans age past peak

**Confidence levels:**
- < 3 shots: "low" — show best shot's grind
- 3-5 shots: "medium" — weighted centroid
- 6+ shots: "high" — weighted centroid with tighter clustering

### Aging Drift Factor
As beans age past peak, they become more brittle and produce fewer fines → shots run faster → need finer grind.
- Peak window (baseline): no adjustment
- 15-30 days post-roast: suggest ~0.5 steps finer
- 30-50 days: suggest ~1-2 steps finer
- 50+ days: suggest ~2-3 steps finer (if still brewing)

### Alternatives Considered
- **Keep quadratic regression + bootstrap:** More statistically rigorous but requires numpy, unstable with <10 points, and bootstrap adds complexity for marginal benefit on a kiosk app.
- **Bayesian optimization / Gaussian process:** Theoretically ideal for small-sample optimization, but massive overkill for a single-user kiosk. Requires scipy or GPy dependency.
- **Ordinal logistic regression:** Respects the discrete 1-5 scale properly, but requires additional libraries (statsmodels) and is harder to interpret for the user.
- **Weighted centroid (chosen):** No dependencies, robust to outliers, naturally handles sparse data, trivially interpretable. Trade-off: doesn't model the underlying score-grind relationship, just points toward what worked best recently.

---

## 2. Diagnostics: Yield-First Priority Chain

**Changes:** Swap output weight deviation above brew time in the diagnostic priority chain.

**New priority:** Taste descriptors → Score dimensions → Output deviation → Brew time

**Rationale:** Brew ratio (output/dose) is the primary driver of extraction percentage. Brew time is a dependent variable of grind, prep, and pressure. If yield is off, fixing that addresses the root cause; time often self-corrects.

### Alternatives Considered
- **Weight all signals equally:** Would produce conflicting or confusing multi-tip output. Priority chain is cleaner for UX.
- **Machine learning classifier on combined signals:** Would need a large labeled dataset of diagnosed shots. Not feasible for single-user app.

---

## 3. Freshness: Roast-Level-Dependent Windows

**Changes:** Shift stage boundaries based on `bean_color` (roast level).

**Windows by roast level:**

| Roast | best_after default | Peak duration | Good duration | consume_within default |
|-------|-------------------|---------------|---------------|----------------------|
| Light | 12 days | 14 days | 14 days | 60 days |
| Medium | 7 days | 11 days | 14 days | 50 days |
| Dark | 4 days | 8 days | 10 days | 35 days |

When `bean_color` is set, auto-adjust the stage boundaries even if user hasn't customized best_after/consume_within.

### Alternatives Considered
- **Continuous decay function (sigmoid/exponential):** Better for internal math (weighting), but loses the intuitive stage labels users see. Hybrid approach: keep stages for UI, use continuous score internally for weighting.
- **User-only customization:** Already supported via best_after/consume_within per coffee, but most users won't change defaults. Roast-based auto-adjustment gives good defaults without user effort.

---

## 4. Freshness: Opened-Date Acceleration

**Changes:** If `opened_date` is set and the bag has been open, accelerate the degradation timeline.

**Model:** After opening, the remaining freshness window compresses. Roughly:
- First 7 days open: no change (still within sealed-equivalent)
- 7-14 days open: advance stage by ~1 (e.g., Peak → Good)
- 14+ days open: advance stage by ~2 (e.g., Good → Fading)

Implementation: compute `days_open` and apply a penalty that shifts the effective `days_since_roast` forward.

### Alternatives Considered
- **Separate opened-vs-sealed freshness tracks:** More accurate but doubles the model complexity. The penalty approach is simpler and close enough.
- **Ignore opened date:** Current approach. Misses a significant real-world factor.

---

## 5. Rating: Quality-Weighted Tiers

**Changes:** Incorporate the user's `overall` score into the tier calculation with 2x weight. Separate quality dimensions from flavor profile dimensions.

**Quality score (for tier):** Weighted average of sweetness, balance, and overall (2x).
```
quality = (sweetness + balance + 2*overall) / 4
```

**Flavor profile (for descriptors):** Still uses acidity, body, aroma thresholds as before.

**Revised tier boundaries:**
| Quality Score | Tier |
|--------------|------|
| >= 4.5 | Outstanding |
| >= 3.8 | Excellent |
| >= 3.0 | Very Good |
| >= 2.2 | Good |
| < 2.2 | Below Average |

### Alternatives Considered
- **Full SCA-style weighting:** Different weights for each dimension based on SCA cupping form. Overly complex for home use and doesn't map cleanly to a 1-5 scale.
- **Overall-only tier:** Simplest, but loses the multi-dimensional signal that makes the tier more stable and informative.
- **Keep equal weighting:** Conflates flavor traits (acidity, body) with quality indicators (sweetness, balance). A mellow coffee and a bright coffee can be equally excellent.

---

## 6. Insights: Forgiveness Metric

**New metric:** Score consistency across varying brew parameters. Measures how tolerant a coffee is of imprecise grinding/timing.

**Calculation:**
```
forgiveness = 1 - (score_stddev / grind_range)
```
Where `score_stddev` is the standard deviation of overall scores and `grind_range` is max_grind - min_grind. Normalized to a qualitative label.

A coffee that scores 3.8-4.2 across grind settings 8-12 is "Highly Forgiving."
A coffee that scores 2.0-4.5 across grind settings 8-10 is "Demanding."

**Labels:**
- Low variance + wide grind range: "Very Forgiving"
- Low variance + narrow grind range: "Consistent" (not enough range to judge)
- High variance + any range: "Demanding"

Requires 4+ evaluated shots with at least 2 different grind settings.

### Alternatives Considered
- **Coefficient of variation (CV):** score_stddev / score_mean. Doesn't account for grind range explored — a coffee only tried at one grind setting would look "forgiving" by CV alone.
- **Regression R² on grind vs score:** Would show how much grind explains score variance, but hard to interpret and requires more data.

---

## 7. Insights: Shot-Weighted Group Averages

**Changes:** When computing group averages (by process, origin, roast), weight each coffee's contribution by its shot count.

**Current:** Average of per-coffee averages (a coffee with 2 shots = a coffee with 20 shots).
**New:** Sum of (coffee_avg × shot_count) / total_shots in group.

### Alternatives Considered
- **Pure shot-level averages:** Would let dial-in shots drag down well-dialed coffees. Per-coffee averages with shot-weighting is the better hybrid.
- **Top-50% filtering (Gemini):** Only average top half of shots per coffee. Good idea but harder to explain to the user and may hide useful variance info.

---

## 8. Insights: Price-Per-Shot Value Metric

**Changes:** Normalize value to cost per shot instead of raw bag price / score.

**Formula:**
```
cost_per_shot = (bag_price / bag_weight_g) * typical_dose_g
value_score = cost_per_shot / avg_overall
```

Uses the coffee's actual `grams_in` from samples (average dose) when available, falls back to 18g default.

### Alternatives Considered
- **Cost per excellent shot (Gemini):** bag_price / count(shots >= 4.0). Penalizes hard-to-dial coffees. Interesting but requires enough shots to be meaningful — can add later as supplementary.
- **Raw price / score (current):** Ignores bag size entirely. A 1kg bag at 30€ looks worse than a 250g bag at 20€.
