# Refactoring Plan — v0.6

Consolidated from 3 independent reviews (Gemini, JS reviewer, Python reviewer).
Updated 2026-04-03.

## Status: 8 of 10 items completed

| # | Task | Status | Impact |
|---|------|--------|--------|
| 1 | XSS: esc() helper in all JS files | DONE | Critical security |
| 2 | render_tasting_notes: local merged dict | DONE | Critical correctness |
| 3 | flask.g DB connection | DEFERRED | Medium performance |
| 4 | parse_coffee_form helper (DRY) | DONE | High maintainability |
| 5 | tasting-emojis.json (single source) | DEFERRED | Medium maintainability |
| 6 | PROCESS_OPTIONS via context processor | DONE | Medium maintainability |
| 7 | Event delegation in JS | DONE | Medium performance |
| 8 | keyboard.js switchLayout helper | DONE | Low code quality |
| 9 | Magic numbers → config constants | DEFERRED | Low maintainability |
| 10 | UPSERT for save_evaluation | DONE | Low code quality |

## Deferred items (low priority)

- **flask.g**: Mechanical refactor touching every route. Current approach works, just creates extra connections.
- **Shared emoji JSON**: Both Python and JS emoji maps work independently. Would need build step or API endpoint.
- **Magic numbers**: Would improve readability but doesn't affect functionality.
