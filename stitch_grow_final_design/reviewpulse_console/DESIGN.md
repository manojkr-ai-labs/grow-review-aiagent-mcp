---
name: ReviewPulse Console
colors:
  surface: '#111417'
  surface-dim: '#111417'
  surface-bright: '#37393d'
  surface-container-lowest: '#0c0e11'
  surface-container-low: '#1a1c1f'
  surface-container: '#1e2023'
  surface-container-high: '#282a2e'
  surface-container-highest: '#333538'
  on-surface: '#e2e2e7'
  on-surface-variant: '#bacac1'
  inverse-surface: '#e2e2e7'
  inverse-on-surface: '#2e3034'
  outline: '#85948c'
  outline-variant: '#3c4a43'
  surface-tint: '#2fe0aa'
  primary: '#44edb7'
  on-primary: '#003828'
  primary-container: '#00d09c'
  on-primary-container: '#00533c'
  inverse-primary: '#006c4f'
  secondary: '#82ffce'
  on-secondary: '#003827'
  secondary-container: '#07e7ad'
  on-secondary-container: '#006348'
  tertiary: '#fecc59'
  on-tertiary: '#3f2e00'
  tertiary-container: '#e0b140'
  on-tertiary-container: '#5d4500'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#59fdc5'
  primary-fixed-dim: '#2fe0aa'
  on-primary-fixed: '#002116'
  on-primary-fixed-variant: '#00513b'
  secondary-fixed: '#42ffc3'
  secondary-fixed-dim: '#00e1a8'
  on-secondary-fixed: '#002116'
  on-secondary-fixed-variant: '#00513b'
  tertiary-fixed: '#ffdf9d'
  tertiary-fixed-dim: '#f0c04d'
  on-tertiary-fixed: '#251a00'
  on-tertiary-fixed-variant: '#5b4300'
  background: '#111417'
  on-background: '#e2e2e7'
  surface-variant: '#333538'
typography:
  editorial-display:
    fontFamily: Newsreader
    fontSize: 2.25rem
    fontWeight: '400'
    lineHeight: 2.75rem
    letterSpacing: -0.02em
  editorial-title:
    fontFamily: Newsreader
    fontSize: 1.5rem
    fontWeight: '400'
    lineHeight: 2rem
    letterSpacing: -0.015em
  editorial-quote:
    fontFamily: Newsreader
    fontSize: 1.125rem
    fontWeight: '400'
    lineHeight: 1.75rem
    letterSpacing: 0em
  headline-lg:
    fontFamily: Geist
    fontSize: 1.75rem
    fontWeight: '600'
    lineHeight: 2.25rem
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Geist
    fontSize: 1.25rem
    fontWeight: '600'
    lineHeight: 1.75rem
    letterSpacing: -0.015em
  headline-sm:
    fontFamily: Geist
    fontSize: 1rem
    fontWeight: '600'
    lineHeight: 1.5rem
    letterSpacing: -0.01em
  body-lg:
    fontFamily: Geist
    fontSize: 1rem
    fontWeight: '400'
    lineHeight: 1.5rem
  body-md:
    fontFamily: Geist
    fontSize: 0.875rem
    fontWeight: '400'
    lineHeight: 1.375rem
  body-sm:
    fontFamily: Geist
    fontSize: 0.75rem
    fontWeight: '400'
    lineHeight: 1.125rem
  tabular-lg:
    fontFamily: JetBrains Mono
    fontSize: 1.25rem
    fontWeight: '500'
    lineHeight: 1.5rem
    letterSpacing: -0.02em
  tabular-md:
    fontFamily: JetBrains Mono
    fontSize: 0.875rem
    fontWeight: '500'
    lineHeight: 1.25rem
    letterSpacing: -0.01em
  tabular-sm:
    fontFamily: JetBrains Mono
    fontSize: 0.75rem
    fontWeight: '400'
    lineHeight: 1rem
    letterSpacing: 0em
  label-caps:
    fontFamily: JetBrains Mono
    fontSize: 0.6875rem
    fontWeight: '600'
    lineHeight: 0.875rem
    letterSpacing: 0.06em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  grid-margin-desktop: 1.5rem
  grid-gutter-desktop: 1rem
  grid-margin-mobile: 1rem
  grid-gutter-mobile: 0.75rem
  density-compact: 0.25rem
  density-cozy: 0.5rem
  density-spacious: 1rem
  container-pad: 1.25rem
---

## Brand & Style

This design system delivers a high-density, analytical workspace engineered for quantitative product intelligence and executive oversight across brokerage, asset management, and capital markets platforms.

### Target Audience & Emotional Intent
- **Operators & Leads:** Product managers, compliance directors, and CX operations requiring instantaneous pattern recognition across tens of thousands of customer signals and regulatory touchpoints.
- **Tone & Posture:** Authoritative, clinical, and quiet. The interface rejects consumer SaaS ornamentation, ambient neon drop-shadows, and speculative AI decorative cues in favor of rigorous tabular efficiency, sharp structural framing, and deliberate editorial clarity.
- **Visual Stance:** Dark Fintech Editorial. The design fuses the institutional discipline of a Bloomberg or FactSet terminal with the balanced typographic pacing of financial reportage. Every pixel is allocated to actionable data density and critical operational telemetry.

## Colors

The palette operates under an absolute dark hierarchical system, balancing low-reflectance structural planes with surgical semantic indicators.

### Canvas & Structural Surfaces
- **App Canvas (`#07090C`):** Base terminal canvas. Pure non-reflective deep charcoal-black.
- **Sidebar & Chrome Navigation (`#0B0F14`):** Fixed navigation anchors and global application headers.
- **Surface Containers (`#10151C`):** Standard interactive cards, module viewports, data grids, and panel view layers.
- **Subtle Surface & Hover Tier (`#161C25`):** Table row hover transitions, secondary segmented toggles, active list states, and popover backdrops.
- **Dividers & Structural Borders (`#243041`):** Structural 1px boundary lines ensuring clean, geometric separation without high-contrast visual noise.

### Typography & Content Color
- **Primary Text (`#F4F7FA`):** Crisp high-contrast off-white for metrics, headlines, and primary data values.
- **Secondary Text (`#9AA8B8`):** Balanced slate for metadata labels, column headers, and structural body copy.
- **Muted Text (`#6B7A8D`):** Deep slate-grey reserved for disabled states, micro-timestamps, and secondary keys.

### Semantic Accents & Status Indicators
- **Primary Accent & Positive Yield (`#00D09C`):** Institutional teal representing Groww core brand parity, positive sentiment shifts, and successful execution benchmarks. Hover state resolves to `#00E6AC`.
- **Negative / Critical Friction (`#FF5A6A`):** High-signal crimson for regulatory complaints, platform latency regressions, and negative sentiment anomalies.
- **Warning / Inspection Target (`#F5B942`):** Amber hue for unassigned surges, moderation backlog alerts, and anomalies.
- **Star & Qualitative Rating Gold (`#F5C451`):** Calibrated warm gold reserved exclusively for multi-star metric distributions, CSAT values, and app-store feedback tracking.

## Typography

The type system implements a tri-font hierarchy:
1. **Editorial Serif (`Newsreader`):** Applied strictly to executive syntheses, verbatim customer complaints, thematic pulse summaries, and top-line operational briefings. It signals distilled human meaning within high-velocity data feeds.
2. **UI Sans (`Geist`):** The primary operational engine. Highly neutral, compact, and optimized for tabular dashboards, dense list items, form fields, and global toolbars.
3. **Tabular Monospace (`JetBrains Mono`):** Dedicated to computational precision. All numeric ratings, currency volumes, deltas, percentages, ISO timestamps, issue keys, and cohort tags must render in monospace with proportional lining numerals disabled in favor of strict tabular spacing.

## Layout & Spacing

The layout is built on a 16-column desktop grid tailored for multi-pane analytical density, collapsing into an 8-column layout on standard viewports and 4 columns on condensed inspection displays.

### Layout Model
- **Fixed App Rail:** 64px collapsed icon rail expanding to 240px drawer for workspace navigation, anchored at `#0B0F14`.
- **Primary Viewport:** 16-column fluid structure bounded by a minimum resolution of 1280px for standard operator consoles. Outer margins sit at `24px` (`1.5rem`) with rigid `16px` (`1rem`) gutters.
- **Rhythm:** Spacing follows a strict 4px/8px micro-scale:
  - `4px`: Inline badge padding, micro tabular separation, and icon-to-label gaps.
  - `8px`: Chip padding, input inner padding, and list element gaps.
  - `16px`: Card-internal section splits and filter-bar stacks.
  - `20px`: Structural card interior padding.
  - `24px`: Module-to-module margin on dashboard rows.

## Elevation & Depth

This system avoids blurred atmospheric drop shadows, neon underglows, and decorative diffused layers. Depth is constructed purely through **Tonal Surface Layering** and **Subtle Structural Framing**.

### Layer Hierarchy
- **Layer 0 (Base Canvas - `#07090C`):** Substrate. Holds application rails and empty canvas regions.
- **Layer 1 (Card & Module Shells - `#10151C`):** Raised working units. Framed by a consistent, non-diffused 1px border of `#243041`.
- **Layer 2 (Embedded Micro-Surfaces - `#161C25`):** Nested metric wells, data table headers, and active segment wells inside cards.
- **Layer 3 (Overlays & Modals - `#10151C`):** Filter panels, popovers, and slide-out issue inspection trays. Framed with a 1px border of `#243041` paired with a sharp, zero-spread anchor shadow: `0 8px 24px -4px rgba(0, 0, 0, 0.85)`. No color tinting is applied to shadows.

## Shapes

The interface balances razor-sharp data structures with calculated, structural radiuses to preserve an industrial, tactile console aesthetic:

- **Cards & Data Modules:** Explicitly set to `12px` border radius (`rounded-card`).
- **Chips, Pill Badges & Status Tags:** Explicitly set to `8px` border radius (`rounded-chip`).
- **Buttons, Text Inputs, Search Bars & Select Fields:** Explicitly set to `6px` border radius (`rounded-control`).
- **Checkboxes & Segment Blocks:** `4px` corner rounding for tight mechanical cohesion.

## Components

### Buttons
- **Primary Execution:** Solid `#00D09C` fill, `#07090C` text, `6px` radius, font weight 600 (`Geist`), 32px height (compact) or 38px (default). Active hover shifts to `#00E6AC`.
- **Secondary / Operational:** Surface `#10151C`, border 1px `#243041`, text `#F4F7FA`. Hover shifts background to `#161C25` with border `#9AA8B8`.
- **Destructive:** Surface transparent, border 1px `#FF5A6A`, text `#FF5A6A`. Hover applies 10% opacity `#FF5A6A` background.
- **Icon Buttons:** Fixed square (32x32px or 28x28px), 1.5px stroke icons, 1px border `#243041`, background `#10151C`.

### Chips & Semantic Badges
- **Shape:** `8px` radius, `0.25rem 0.5rem` padding. Font: `JetBrains Mono`, 11px uppercase (`label-caps`).
- **Positive / Yield Status:** 10% tint `#00D09C` background, 1px border `#00D09C` (at 40% alpha), text `#00D09C`.
- **Negative / Complaint Spike:** 10% tint `#FF5A6A` background, 1px border `#FF5A6A` (at 40% alpha), text `#FF5A6A`.
- **Warning / Pending Audit:** 10% tint `#F5B942` background, 1px border `#F5B942` (at 40% alpha), text `#F5B942`.
- **Neutral Metric / Version Tag:** `#161C25` surface, 1px border `#243041`, text `#9AA8B8`.

### Cards & Container Panels
- Surface: `#10151C`, Border: 1px `#243041`, Radius: `12px`, Internal padding: `20px`.
- Headers feature a bottom 1px divider (`#243041`) separating module controls and action triggers from internal content.

### Data Tables & Review Streams
- Row Height: Strict 40px (compact) or 48px (detailed).
- Borders: Horizontal 1px border `#243041` between rows. No vertical interior borders.
- Header: Text in `#6B7A8D`, uppercase `JetBrains Mono` 11px, background `#0B0F14` or sticky `#10151C`.
- Hover state: Background transition to `#161C25`.
- Numeric Cells: Aligned right, rendered in `JetBrains Mono` with negative/positive delta sign prefixes.

### Text Inputs & Global Filters
- Background: `#07090C`, 1px border `#243041`, Radius: `6px`.
- Text: `#F4F7FA`, Placeholder: `#6B7A8D`.
- Focus Ring: 1px sharp outline `#00D09C` with no diffused external glow.

### Star Ratings & Sentiment Modules
- Star iconography rendered at 14px size, static `#F5C451` fill with 1.5px stroke boundaries.
- Fractional aggregates (e.g., `4.38 / 5.00`) accompany stars using tabular `JetBrains Mono` in `#F4F7FA`.

### Editorial Pulse & Analysis Synthesis Callouts
- Enclosed quote/synthesis box using surface `#161C25` with a vertical 2px solid anchor line on the left edge in `#00D09C`.
- Synthesis body rendered using `Newsreader` regular at 16px or 18px (`editorial-quote`), giving qualitative summaries an authoritative, long-form editorial presence directly adjacent to high-speed metric columns.