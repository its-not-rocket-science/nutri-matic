# Brand identity — NM-3

## Brief

Nutri-Matic runs real digestibility science (DIAAS/PDCAAS, provenance-tracked
micronutrients) with the straight-faced over-precision of a machine built to
measure something ordinary to twelve decimal places — the same joke Douglas
Adams' Nutri-Matic Drink Synthesizer told about tea. None of Hitchhiker's
Guide branding or iconography is quoted or reproduced; the inheritance is
tone, not imagery: a mid-century calibration instrument that takes a bowl of
chickpeas exactly as seriously as a mass spectrometer.

## Logomark

A 270° analogue gauge with the needle resting past 100% — the same dial
language used for every DIAAS/nutrient readout in the app (see
`ScoreCard.svelte`, `NutrientBars.svelte`), just facing outward as the mark.

- Clearance: keep a margin equal to the mark's radius on every side.
- Minimum lockup width: 96px.
- The needle always rests upper-right (the "reading well" position). Never
  redraw it pointing down or left — that reads as a fault indicator
  elsewhere in the system (see the low-nutrient gauge in the dashboard).

Source: `frontend/src/lib/assets/favicon.svg`; PWA icons in
`frontend/static/icons/` (192/512/maskable/apple-touch), regenerated from the
same mark.

## Palette

Six named values, defined as CSS custom properties in `frontend/src/app.css`
(light values first, dark-mode overrides in the `prefers-color-scheme: dark`
block and the `data-theme` overrides used by the in-app theme toggle):

| Token | Light | Role |
|---|---|---|
| `--color-primary` | `#1b4b4a` (Instrument Teal) | Chassis / primary actions |
| `--color-accent` | `#c9821f` (Phosphor Amber, deepened for AA text contrast) | Needle / signal accent — used sparingly |
| `--color-bg` / `--color-surface` | `#f1ead9` / `#fbf7ee` (Parchment) | Page ground / card surface |
| `--color-text` | `#2a2622` (Graphite) | Ink |
| `--color-success` | `#4c7c6e` (Verdigris) | Measured / good status |
| `--color-danger` | `#a8402f` (Signal Red) | Limiting / alert status |

Teal and amber are the only two doing expressive work. Verdigris, signal-red,
and the neutrals stay quiet — semantic status color is deliberately separate
from the two brand accents.

Dark mode is the instrument lit at night (graphite-green chassis, phosphor
teal/amber glow), not an inverted light theme — see the dark-mode token
block in `app.css` for the actual values.

## Type

- **Display** (`--font-display`): Futura, with Century Gothic/Avenir Next/URW
  Gothic fallbacks — a genuine mid-century geometric face with real
  1960s technical-equipment lineage. Used for headings, the nav brand
  lockup, buttons, table headers, and short uppercase labels.
- **Body** (`--font-sans`): the existing system sans stack. Nutri-Matic is a
  data-dense UI that gets scanned, not read, so legibility beats character
  for paragraphs, forms, and table content — the display face is reserved
  for structural/short text, never body copy.
- **Data** (`--font-mono`): system monospace, used wherever digits must line
  up (nutrient tables, DIAAS/PDCAAS scores) — `font-variant-numeric:
  tabular-nums` is applied alongside it.

## Applying it

- Headings (`h1`–`h4`) get `--font-display` automatically; only short
  structural labels (buttons, table headers, the `.label-caps` utility) are
  forced uppercase — user content (a recipe or food name as an `h1`) is
  never transformed.
- New button variant `.btn-accent` (amber) exists alongside
  `.btn-primary`/`.btn-secondary`/`.btn-danger` for the rare case a signal
  accent is warranted (e.g. an "Optimise" call to action) — don't reach for
  it as a general-purpose primary button.
- `--color-focus-ring` is the amber accent, not the primary teal — a
  deliberate detail (the "needle" motif doubles as the attention/focus
  indicator).
