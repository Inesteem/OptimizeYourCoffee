# Extraction Diagnostics Reference

Source: Perplexity research, SCA extraction science.

## Overview

The `diagnose()` function identifies extraction problems from taste descriptors and scores. It provides **observational feedback** — what went wrong and why. Grind size adjustment suggestions are handled by the grind optimizer (Settings → Grind Optimizer).

## Taste → Extraction Mapping

| Taste | Extraction | Meaning |
|-------|-----------|---------|
| Sour, acidic | Under | Not enough extraction |
| Thin, watery | Under | Insufficient body from low extraction |
| Flat | Under | Underdeveloped flavors |
| Bitter | Over | Too much extraction |
| Harsh | Over | Aggressive over-extraction |
| Astringent, dry | Over | Tannin-like over-extraction |
| Ashy | Over | Burnt extraction character |
| Sour AND bitter | Channeling | Uneven extraction — fix puck prep |
| Earthy | Ambiguous | Only adjust if also bitter/harsh |
| Smoky | Ambiguous | Check if also bitter; may be roast profile |

## Diagnostic Priority

1. **Taste descriptors** (primary): Under-extraction signs vs over-extraction signs. Both present → channeling diagnosis.
2. **Score dimensions** (fallback): Used when no taste descriptors selected. High acidity + low sweetness → under-extracted, etc.
3. **Brew time** (informational): Very fast (<20s) or very slow (>35s) shots noted without grind advice.
4. **Output deviation** (informational): Large deviations (>5g) from target noted without grind advice.

## Severity Detection

| # of under/over descriptors | Combined with scores | Diagnosis |
|----------------------------|---------------------|-----------|
| 1 descriptor | — | Signs of under/over-extraction |
| 2+ descriptors | Confirming score | Strongly under/over-extracted |
| 3+ descriptors | — | Strongly under/over-extracted |
| Both under AND over | — | Channeling — fix puck prep first |

## Score-Based Fallbacks

When no taste descriptors are selected:

| Pattern | Diagnosis |
|---------|-----------|
| Acidity ≥4, sweetness ≤2, body ≤2 | Likely under-extracted |
| Acidity ≥4, sweetness ≤2 | Slightly under-extracted |
| Acidity ≤2, sweetness ≤2 | Likely over-extracted |
| Body ≤2, sweetness ≥3 | Thin body — consider dose increase |

## Informational Observations

These are shown as context, not as grind adjustment advice:

- **Fast shot** (<20s): Noted with target range (25-30s)
- **Slow shot** (>35s): Noted with choke warning
- **Output deviation** (>5g off target): Noted with actual vs target values

## Positive Feedback

- Balance ≥4 AND overall ≥4: "Great shot! Save this recipe as a reference."
- Overall ≥4 with no issues: "Solid shot. Minor tweaks could make it even better."

## Relationship to Grind Optimizer

The diagnostics and grind optimizer serve different purposes:
- **Diagnostics** (eval page): Immediate feedback on *this* shot — what went wrong
- **Grind optimizer** (sample page): Statistical suggestion for *next* shot — where to set the grind

The grind optimizer can be configured to optimize for taste score, ratio accuracy, or individual dimensions. The diagnostics remain taste-focused regardless of optimizer settings.

## Target Parameters
- Extraction time: 25-30 seconds
- Weight ratio: 1:2 (e.g. 18g → 36g)
- Water temperature: 88-92°C
