# Codename Ariadne — Phase 1 Design System

- Status: implementation specification
- Date: 2026-07-11
- Theme: serious, premium cyberpunk intelligence console
- Runtime: local React/Tauri interface; assets and fonts packaged locally
- Privacy: examples and component specimens use synthetic generic content and reserved `.invalid` hosts only

## 1. Design position

Codename Ariadne should feel like a disciplined analytical instrument: dark, exact, calm under load, and unmistakably local. Its cyberpunk character comes from material contrast, signal color, precise typography, subtle route/grid motifs, and responsive operational feedback—not from constant glow, theatrical copy, or game-like chrome.

The visual hierarchy must communicate four priorities in this order:

1. **Safety and scope** — lock state, synthetic/real state, transmission policy, sensitivity, and unresolved limitations.
2. **Decision and action** — what requires human review, what can run, and what is blocked.
3. **Evidence and provenance** — source, capture state, contradictions, and why a relationship exists.
4. **Operational density** — progress, coverage, tasks, graph structure, and historical change.

## 2. Design principles

### Instrument, not spectacle

Animation, glow, grid, waveform, and scan motifs only communicate a real state or orient the eye. A static screen should still look complete and premium.

### Layer by purpose

Use opaque graphite surfaces for sustained reading, translucent glass only for temporary overlays or inspectors, and metal-like separators for shell structure. Do not put every metric in an isolated glowing card.

### One accent at a time

Cyan is the primary interactive accent. Ultraviolet marks human judgment/manual review. Green, amber, and rose are reserved for semantic status. A region should rarely contain more than one bright accent unless it is explicitly a status comparison.

### Dense without becoming small

Density comes from alignment, grouping, progressive disclosure, and tabular numerals—not from tiny text or compressed hit targets.

### Uncertainty is visible

Source outcome, ownership, confidence, sensitivity, provenance, and time are separate labels. A single score, color, or glow must never suggest certainty.

### Local-first is tangible

The shell always communicates vault state and whether an action stays local or could disclose data. External transmission is visually distinct from ordinary navigation.

## 3. Brand language

### 3.1 Product identity

- Primary wordmark: **Codename Ariadne**.
- Technical subsystem: **Ariadne Core**, used only for correlation and attribution explanations.
- Optional short shell label at compact width: **Ariadne**, with the full product name in the accessible label and window title.
- Functional labels remain plain: Mission Control, Findings, Link Map, Source Radar, Case Desk, Compare Runs, and Removal Tracker.

### 3.2 Signature motif

The signature motif is a single fine “thread route”: a line that changes direction at deliberate nodes. It may appear in the wordmark, selected navigation marker, section divider, or initial loading trace.

Rules:

- Use one thread motif per composition, never as a repeated border on every panel.
- Nodes correspond to real steps, events, or data where possible.
- The motif is decorative when used in branding and must be hidden from assistive technology.
- Never use a literal maze as an interaction obstacle or a mythological illustration that competes with content.

### 3.3 Voice

Copy is precise, restrained, and non-accusatory.

| Prefer | Avoid |
|---|---|
| “Possible match — review required” | “Target acquired” |
| “Provider did not return a match” | “Account does not exist” |
| “Access blocked; guided capture available” | “Bypass failed” |
| “Simulated run — no external requests” | “Live scan” when it is mocked |
| “Prepare draft” | “Launch report” |
| “Unresolved limitations” | “Total coverage” |

Sentence case is the default. Uppercase is limited to short technical codes and small navigation/status eyebrows.

## 4. Foundation tokens

Tokens are semantic CSS custom properties exposed through the design-system package. Components consume semantic names, never raw palette values. The initial theme is dark; a high-contrast remap is required before adding a light theme.

### 4.1 Core color palette

| Token | Value | Role |
|---|---:|---|
| `--ink-1000` | `#06080C` | Window surround and deepest backdrop |
| `--ink-950` | `#090C12` | Main canvas background |
| `--graphite-900` | `#0F141D` | Navigation and sustained-reading surface |
| `--graphite-850` | `#131A25` | Primary panel |
| `--graphite-800` | `#182230` | Raised panel and selected row |
| `--graphite-750` | `#202B3A` | Input and active control surface |
| `--metal-650` | `#2B3849` | Strong border and divider |
| `--metal-700` | `#243041` | Default border |
| `--mist-100` | `#F3F7FC` | Primary text |
| `--mist-250` | `#C7D1DE` | Secondary text |
| `--mist-400` | `#94A3B6` | Muted text and metadata |
| `--mist-600` | `#667487` | Disabled text/decorative marks only |
| `--signal-cyan` | `#58DFF5` | Primary action, selection, focus support |
| `--signal-cyan-soft` | `#A2F1FC` | High-emphasis text/icon on dark surfaces |
| `--signal-violet` | `#B99CFF` | Human judgment, manual review, correlation |
| `--signal-green` | `#70E5A2` | Success/healthy/verified integrity |
| `--signal-amber` | `#F4B860` | Caution, blocked, rate limit, retention unknown |
| `--signal-rose` | `#FF7B8D` | Failure, destructive action, integrity warning |
| `--signal-blue` | `#8AB4FF` | Informational and historical context |

Bright signals are not used as large-area backgrounds. Filled controls use a darker foreground selected for contrast; outlined and tinted treatments are the default for status.

### 4.2 Semantic color tokens

```css
:root {
  color-scheme: dark;

  --color-canvas: var(--ink-950);
  --color-shell: var(--graphite-900);
  --color-surface: var(--graphite-850);
  --color-surface-raised: var(--graphite-800);
  --color-surface-control: var(--graphite-750);
  --color-overlay: rgb(15 20 29 / 92%);
  --color-scrim: rgb(2 4 7 / 72%);

  --color-border: var(--metal-700);
  --color-border-strong: var(--metal-650);
  --color-border-subtle: rgb(148 163 182 / 14%);

  --color-text: var(--mist-100);
  --color-text-secondary: var(--mist-250);
  --color-text-muted: var(--mist-400);
  --color-text-disabled: var(--mist-600);

  --color-accent: var(--signal-cyan);
  --color-accent-strong: var(--signal-cyan-soft);
  --color-focus: #A2F1FC;
  --color-selection: rgb(88 223 245 / 16%);

  --color-info: var(--signal-blue);
  --color-success: var(--signal-green);
  --color-warning: var(--signal-amber);
  --color-danger: var(--signal-rose);
  --color-review: var(--signal-violet);
}
```

### 4.3 Contrast rules

- Normal text targets at least 4.5:1; large text and essential non-text UI target at least 3:1.
- Primary and secondary text tokens are the only defaults for paragraph copy. Muted text is for supplementary content and must be tested on its actual surface.
- Disabled color never carries information that the user must read.
- A focus indicator uses a 2 px high-contrast ring plus a 2 px offset/halo so it survives both dark and accent-filled controls.
- Status always includes text and, where useful, an icon or pattern. Color is redundant.
- High-contrast and `forced-colors` modes replace glow/shadow with solid outlines and preserve selection/focus.
- Token/component combinations are validated with automated axe checks and manual inspection; a palette value is not assumed accessible in every combination.

## 5. Typography

### 5.1 Families

| Role | Family | Use |
|---|---|---|
| Interface | Inter Variable, system sans-serif fallback | Navigation, forms, headings, prose, tables |
| Data | IBM Plex Mono Variable, `ui-monospace` fallback | IDs, URLs, hashes, timestamps, queries, logs, numeric telemetry |

Both fonts are packaged as subsetted local WOFF2 assets with licenses. No font request leaves the device. If a font fails, the system fallback must preserve layout and legibility.

### 5.2 Type scale

| Token | Size / line-height | Weight | Use |
|---|---:|---:|---|
| `--type-display` | 30 / 36 px | 600 | Rare Mission Control title/empty-state statement |
| `--type-h1` | 24 / 30 px | 600 | One page heading |
| `--type-h2` | 18 / 24 px | 600 | Major section |
| `--type-h3` | 15 / 22 px | 600 | Panel title |
| `--type-body` | 14 / 21 px | 400 | Default prose/forms |
| `--type-body-strong` | 14 / 21 px | 600 | Emphasised values and labels |
| `--type-dense` | 13 / 18 px | 400 | Dense tables and operational rows |
| `--type-label` | 12 / 16 px | 600 | Short labels, badges, eyebrows |
| `--type-code` | 12.5 / 18 px | 450 | Logs, IDs, queries, hashes |

Essential prose, actions, status labels, and decision text are never smaller than
11 px in the compact desktop interface. A 10 px floor is reserved for auxiliary
machine metadata such as timestamps, edge annotations, and abbreviated hashes;
the complete value must remain available in an adjacent detail or accessible
representation. Nothing renders below 10 px. Uppercase labels use at most 0.08
em letter spacing and no more than three words. Body text line length is
normally 55–80 characters.

### 5.3 Numeric and technical data

- Use tabular numerals for counters, costs, times, scores, and task tables.
- Use slashed zero in technical identifiers where the font supports it.
- Do not letter-space URLs, hashes, or user-entered values.
- Long technical values wrap at safe delimiters in details and use middle truncation in rows; the complete value remains available through details/copy.
- Hashes display an algorithm prefix and grouped visible segments; integrity state sits beside, not inside, the hash.

## 6. Spacing, sizing, and geometry

### 6.1 Spacing scale

```text
space-0  0
space-1  2 px
space-2  4 px
space-3  8 px
space-4  12 px
space-5  16 px
space-6  20 px
space-7  24 px
space-8  32 px
space-9  40 px
space-10 48 px
space-12 64 px
```

Use 16 px panel gaps and 24 px page rhythm at standard width; compact mode uses 12 px gaps and 16 px page padding. Dense rows are 40 px minimum. Default interactive controls are 40 px high; compact secondary controls may be 32 px only when they still meet target-spacing requirements and have an accessible alternative.

### 6.2 Radius and cut

| Token | Value | Use |
|---|---:|---|
| `--radius-xs` | 3 px | Tags and tiny status marks |
| `--radius-sm` | 6 px | Inputs, buttons, rows |
| `--radius-md` | 10 px | Panels and menus |
| `--radius-lg` | 14 px | Drawers/dialogs and hero surfaces |
| `--cut-signal` | 8 px | Optional clipped top-right corner on one featured panel |

The clipped “signal” corner is a restrained brand detail. It is not applied to fields, data rows, dialogs, or every card.

### 6.3 Layout tokens

| Token | Wide | Standard | Compact laptop |
|---|---:|---:|---:|
| Navigation width | 232 px | 208 px | 68 px |
| Inspector width | 360 px docked | 340 px overlay/pinned if space | modal sheet |
| Page inline padding | 32 px | 24 px | 16 px |
| Page block padding | 24 px | 20 px | 16 px |
| Content grid | 12 columns | 12 columns | 4 columns |
| Grid gap | 20 px | 16 px | 12 px |

All main-content flex/grid children set `min-inline-size: 0`. The page canvas has no arbitrary narrow maximum width; reading sections constrain their own measure while data/graph views use available space.

## 7. Surfaces and depth

Depth comes from luminance, border strength, and occlusion before shadow or blur.

| Level | Treatment | Examples |
|---|---|---|
| Canvas | Near-black with optional 24 px grid at 3–4% opacity | Main route background |
| Shell | Opaque graphite, strong separating seam | Navigation and title bar |
| Panel | Opaque graphite, 1 px subtle border | Tables, forms, timelines |
| Raised | Slightly lighter fill, stronger top/left edge | Selected task, active comparison |
| Overlay | 92% opaque graphite, modest 12 px blur, strong outline | Command palette, inspector, menu |
| Critical | Normal surface plus semantic leading rail and heading | Transmission hold, integrity warning |

Rules:

- Scanlines are limited to non-reading backdrops at 2% opacity and are disabled in reduced-motion/high-contrast modes.
- Blur is never required to understand separation and is removed when transparency reduction is requested.
- Glow is a small selected/focus halo, not a panel shadow.
- Shadows remain soft and neutral; neon-colored shadows are reserved for active focus/selection only.
- Sustained text never sits directly over a grid, image, animated waveform, or transparent busy background.

## 8. Iconography and imagery

- Use Lucide icons at 16, 18, or 20 px with a consistent 1.75 px stroke.
- Every unfamiliar icon has a visible label or accessible name and tooltip. Icon-only primary actions are prohibited.
- Status icons are stable: check/verified, minus/not-found, pause/not-checked, warning/blocked, key/auth-required, clock/rate-limited, disconnect/unavailable, split/ambiguous, person-check/manual-review.
- Do not use emoji as functional icons.
- Illustrations, if any, are abstract route/provenance diagrams rendered locally. No stock portraits, real maps with private markers, surveillance imagery, weapons, or faces appear in default empty states.

## 9. Semantic status system

### 9.1 Status treatments

| Meaning | Tone | Shape/treatment |
|---|---|---|
| Found / healthy / hash verified | Green | Tinted badge with check icon |
| Not found for this check | Neutral | Outline badge with minus icon |
| Not checked / paused | Muted blue-grey | Outline badge with pause icon |
| Failed / integrity problem | Rose | Tinted badge with warning icon |
| Blocked / rate limited / retention unknown | Amber | Tinted badge with named reason icon |
| Auth required / manual review / human decision | Violet | Outline/tinted badge with person/key icon |
| Informational / historical | Blue | Outline badge with info/history icon |

`AUTHORITATIVE_ABSENCE` is never shortened to `NOT_FOUND`; it uses an explicit authoritative-source label and explanation.

### 9.2 Evidence-dimension composition

A standard finding header uses separate, consistently ordered fields:

```text
[check outcome] [visibility] [attribution state] [confidence band]
[sensitivity] · [current/historical] · [provider + capture time]
```

The check-outcome badge owns the strongest semantic color. Other dimensions use distinct icons, outlines, labels, and explanatory text so the header does not become a row of competing neon pills.

### 9.3 Confidence

Confidence is displayed as:

1. named band (`Low`, `Moderate`, `High`, or `Unresolved`);
2. visible supporting and contradicting signal counts;
3. explanation and missing-evidence list;
4. optional numeric score and scoring-version details.

Never use a circular “truth meter,” celebratory animation, or green percentage as an ownership decision.

## 10. Core component specifications

### 10.1 `AppShell`

- Exposes title bar, navigation, context bar, main, optional inspector, and activity strip slots.
- The vault and **Synthetic data** state remain visible at every canonical route.
- Compact navigation retains accessible names and shows labels on focus/hover; the active state is a filled rail marker plus `aria-current`.
- The main region receives route focus without forcing the user through the rail again.

### 10.2 `PageHeader`

- One `h1`, optional eyebrow/breadcrumb, short status line, and up to two visible actions.
- Safety status or unresolved limitation precedes secondary metrics.
- Overflow actions live in a labelled menu, not a row of unlabeled icons.

### 10.3 `Panel`

Variants: default, raised, attention, critical, and inspector. Panels use a heading, optional description/action, and content area. Nested panels should generally become sections separated by dividers to avoid “boxes inside boxes.”

### 10.4 Buttons

| Variant | Use |
|---|---|
| Primary | One route/step completion action |
| Secondary | Common safe alternative |
| Quiet | Low-emphasis contextual action |
| Danger | Destructive/cancel action after clear consequence |
| Transmission | Explicit external-disclosure action with outbound/shield icon |

All variants implement default, hover, pressed, focus-visible, disabled, and loading states. Loading preserves width and label context. A disabled button is accompanied by visible prerequisite text when the reason is not obvious.

### 10.5 Forms and input

- Labels are persistent and above controls; placeholder text is an example, never the label.
- Help and error text occupy a stable region to reduce layout jump.
- Sensitivity and locality appear adjacent to fields that accept identity data.
- Paste/drop areas expose supported types, maximum size, local-processing state, and quarantine behavior before interaction.
- Password-, token-, financial-, and document-shaped content uses a restricted-value pattern that masks without echoing the original.
- Toggles are reserved for immediate binary settings; consequential choices use radio groups and explicit save/approve actions.

### 10.6 `Stepper`

- Uses numbered steps with text state (`Current`, `Complete`, `Needs review`, `Locked`).
- It is an ordered list; color/checkmarks are redundant.
- Compact mode shows current step plus “Step n of 7,” with a disclosure for the full list.
- Later steps cannot be entered before prerequisites, but their names and requirements remain visible.

### 10.7 Tables and dense lists

- Use semantic tables for read-mostly aligned data and an ARIA grid only when spreadsheet-like cell interaction is genuinely needed.
- Sticky headers use opaque backgrounds and a bottom seam.
- Rows have 40 px minimum height, clear selected/focus states, and a linked primary label.
- Column priority controls responsive removal; hidden data moves to row disclosure.
- IDs, costs, durations, and timestamps use the data font and tabular numerals.
- Bulk actions appear only after selection and announce the selection count.
- Virtualisation must preserve focus, reading order, row count, and screen-reader alternatives.

### 10.8 Badges and tags

- Badges communicate a controlled status vocabulary and include an icon/text pair where space permits.
- Tags describe user labels or filters and are visually quieter.
- Avoid more than four badges on one line; move secondary dimensions to a labelled metadata row.

### 10.9 Alerts, banners, and toasts

- Inline alert: local context and recovery.
- Page banner: route-wide degraded/safety state.
- Global banner: vault/service condition only.
- Toast: confirms a reversible, already-completed action; never carries the only error details, approval request, or sensitive value.
- Critical transmission and destructive actions use a dialog/sheet, not a toast.

### 10.10 Dialogs, sheets, and inspectors

- Dialogs are for a bounded decision; sheets are for contextual review; inspectors are non-blocking on wide screens.
- A visible title and close action are mandatory.
- Focus is contained only for modal content and restored on close.
- Nested modals are prohibited. A transmission preflight replaces or steps within the initiating sheet.
- At 1100 px, the inspector becomes a modal sheet with a sticky close/header and safe-area padding.

### 10.11 Progress and operational metrics

- Determinate progress shows completed/total plus percentage; indeterminate progress is used only when the total is genuinely unknown.
- ETA, cost, findings, and coverage are individually labelled and timestamped.
- Progress completion never implies coverage completeness.
- Simulated Phase 1 progress always displays **Simulated run — no external requests** adjacent to the progress label.
- A waveform or pulse is allowed only while work is active; paused, blocked, failed, and reduced-motion states are static.

### 10.12 Terminal log

- Uses the data font on an opaque surface, with timestamp, level, task, and redacted message columns.
- Wrapping is on by default; horizontal scrolling is limited to raw structured details.
- A filter and pause-autoscroll control precede the log.
- New rows never steal focus. A throttled textual summary provides screen-reader progress.
- Synthetic log entries contain only generic task IDs and `.invalid` hosts.

### 10.13 `TransmissionPreflight`

- Uses a strong amber/cyan boundary, not danger red unless policy is violated.
- Shows payload category, exact/masked state, provider, operator/hosting regions, access basis, purpose, retention knowledge, estimated cost/duration, risk, and current policy result.
- Actions are `Approve once`, `Deny`, and `Return to edit`; there is no preselected approval.
- Highly sensitive values require a separate explicit checkbox/statement scoped to the run.
- Restricted values show a quarantine explanation and no approval control.

### 10.14 Evidence artifact

- Preview, type, capture time, source URL, HTTP/redirect metadata, viewport/method, SHA-256, encryption state, and redaction state are separate fields.
- The integrity badge says hash verified/tamper warning; it does not say the source claim is true.
- Sensitive previews start redacted. Reveal is explicit and visually persistent for the session.
- Missing/blocked artifacts retain their metadata and offer lawful manual import when applicable.

## 11. Specialised visual systems

### 11.1 Identity and provenance graph

The graph is analytical, not decorative.

Node encoding:

| Dimension | Encoding |
|---|---|
| Node type | Shape plus icon; color is secondary |
| Public/private | Solid versus double/keylined boundary |
| Current/historical | Full versus reduced fill plus explicit label in details |
| Selected | 2 px cyan ring and stable halo |
| Needs review | Violet corner mark plus text in inspector |
| Contradicted | Rose notch/marker, never red fill alone |

Edge encoding:

- Supported: solid line.
- Possible: dashed line.
- Contradicted: interrupted/double-marked line.
- Temporal/historical: dotted line plus date in inspector.
- Direction: arrow only when the domain relationship is directional.
- Animated flow: active tasks only, limited to the selected path; static in reduced-motion mode.

Graph behavior:

- The default layout is deterministic in screenshot/tests.
- Labels appear by focus/selection and by priority at overview zoom; do not render an unreadable label cloud.
- A selected edge opens “Why is this connected?” with source, confidence, visibility, time, evidence, origin, explanation, and contradictions.
- Private-node hiding updates both canvas and alternative list and announces the count hidden.
- A synchronised table/tree is always available for keyboard and screen-reader use.

### 11.2 Geographic map

- Private locations default to coarse regions and never expose exact coordinates in labels, accessible names, screenshots, or initial viewport.
- Public/private and current/historical distinctions use shape/pattern plus labels.
- Provider jurisdiction overlay is visually separate from identity location data.
- Map tiles are a local/approved dependency boundary. A tile failure yields a useful region list and does not erase findings.
- Motion-based fly-to transitions become immediate focus changes under reduced motion.

### 11.3 Coverage and comparison visuals

- Use matrices, bars, and compact tables only when backed by actual or explicitly simulated values.
- Coverage charts always expose checked, not checked, failed, blocked, and unknown portions; no single “coverage score” hides them.
- Comparison uses labelled state chips (`NEW`, `CHANGED`, `REMOVED`, `REAPPEARED`, and others), before/after values, and source/coverage context.
- `REMOVED`, `DEINDEXED`, and `ARCHIVED` have different symbols and explanatory copy.

### 11.4 Timelines

- Time flows top-to-bottom by default for scanability; comparison may use two aligned columns.
- Source-capture time, claimed event time, account activity, ownership period, and user decision time use distinct row labels.
- Approximate, inferred, and exact dates are visibly distinguished.
- Timeline color never substitutes for the event/type label.

## 12. Screen composition recipes

These recipes define the first visual hierarchy, not fixed pixel-perfect wireframes.

### Mission Control — `/dashboard`

- Top: local/synthetic posture and any urgent human decision.
- Middle: active run or start-audit action; recent audits and unresolved findings.
- Bottom: coverage matrix, provider degradation, remediation deadlines, and documented limits.
- Avoid a wall of equal metric cards. Use one status band, one attention queue, and aligned compact metrics.

### New Audit — `/audits/new`

- Main form occupies the reading column; scope/locality summary is a calm right panel on wide screens and follows the form on compact screens.
- Step progression uses one cyan primary action.
- Local-only is the visible baseline, not a hidden default.

### Intake — `/audits/new/intake`

- Split source editor and parsed-segment inventory at wide width; stacked editor then segments at compact width.
- Restricted/quarantined content has a persistent leading warning rail and masked summary.
- Parsing state changes the specific source row, not the entire page.

### Entity Review — `/audits/new/entities`

- Review counts and unresolved conflicts lead.
- Dense grouped table/list owns the canvas; inspector explains provenance, variants, sensitivity, and decision history.
- Batch actions cannot override restricted policy and must preview the affected count.

### Tool Console — `/tools`

- Search and risk/capability filters lead.
- Tool cards are restrained list tiles with name, one-line function, input types, locality, and availability.
- Selecting a tool creates a focused configure workspace rather than navigating through opaque product names.

### Operations — `/operations/:runId`

- Top status band: simulated/real label, current phase, determinate progress, ETA, cost, and controls.
- Middle: queue/worker metrics plus provider task table.
- Bottom: structured log and human-action requests. The log does not dominate the initial viewport.
- Failures and blocks remain in the task table after completion.

### Findings — `/findings`

- Saved review queues and coverage limitations lead.
- Filter bar stays compact; the finding table/list uses separate columns for outcome, attribution, confidence, sensitivity, source, and time.
- Inspector can preview but canonical detail navigation remains `/findings/:findingId`.

### Finding detail — `/findings/:findingId`

- Claim and check outcome lead; attribution decision follows rather than replacing them.
- Two-column wide layout: explanation/signals/contradictions and provenance/evidence.
- Evidence preview begins redacted when needed; hash integrity language remains precise.

### Link Map and map — `/graph`, `/map`

- Canvas dominates, but page heading, privacy mode, filters, search, legend, and alternative list remain reachable.
- Selected detail uses an inspector; compact mode uses a sheet.
- Decorative radar/grid language stays behind controls and content.

### Impersonation case — `/cases/impersonation/:caseId`

- Status language is careful and human-controlled.
- Ownership/activity timeline and identifier comparison occupy equal visual weight.
- Supporting evidence, contradictions, and missing evidence coexist.
- “Prepare draft” is secondary; there is no send/submit action.

### Compare — `/compare`

- Pair/scope compatibility leads.
- State summary is followed by a filterable change table and a synchronised before/after inspector.
- Incompatible coverage uses a prominent amber explanation without disabling all useful comparison.

### Removal Tracker — `/remediation`

- Attention/deadline summary leads.
- Wide mode supports board or list; compact mode is a grouped vertical list.
- Each case exposes jurisdiction, request type, draft status, evidence, response, appeal, and reappearance.
- External action always remains a reviewed draft in Phase 1.

### Source Radar — `/providers`

- Coverage gaps and outages lead before provider catalog volume.
- Rows expose health time, access basis, operator/hosting jurisdiction, transmission, retention, risk, auth, terms, and removal route.
- Brokers are visibly disabled by default; unknown retention is amber and named.

### Transmission — `/privacy/transmission`

- Current mode and pending approvals lead.
- Policy controls, provider allow/block results, and risk matrix follow.
- The ledger is a separate section with masked values by default and no unnecessary plaintext duplication.

### Privacy & Settings — `/settings/privacy`

- Privacy posture/auto-lock/encryption lead.
- Tabs group data/retention, export/redaction, connectors, local AI, and appearance/motion without inventing extra canonical routes.
- Save state is explicit; consequential changes explain scope and restart/relock needs.

### State laboratory — `/states`

- A left specimen selector and top control strip choose component/screen, state, density, contrast, motion, and synthetic fixture.
- The specimen is rendered at exact screenshot dimensions when requested.
- The route carries no production data and is excluded from standard production navigation/builds.

## 13. Motion system

### 13.1 Tokens

| Token | Duration | Use |
|---|---:|---|
| `--motion-instant` | 80 ms | Press/focus feedback |
| `--motion-fast` | 140 ms | Hover, badge, small disclosure |
| `--motion-base` | 220 ms | Drawer, panel, route content transition |
| `--motion-slow` | 360 ms | Graph layout settle, large context transition |

```css
:root {
  --ease-standard: cubic-bezier(.2, .8, .2, 1);
  --ease-enter: cubic-bezier(.16, 1, .3, 1);
  --ease-exit: cubic-bezier(.4, 0, 1, 1);
}
```

### 13.2 Permitted motion

- Opacity plus at most 8 px translation for entering content.
- Drawer/sheet movement tied to spatial origin.
- Selected graph path flow only during active work.
- Progress fill and count interpolation when values truly change.
- One slow, low-contrast scanning line in an active operational panel, never across inputs or text.

### 13.3 Prohibited motion

- Flicker, chromatic jitter, rapid pulses, parallax, auto-panning maps, looping decorative graphs, glitch text, or animated scanlines behind reading content.
- Bouncing attention controls or celebratory effects for findings/identity matches.
- Indeterminate animation after a task is paused, blocked, failed, or awaiting approval.
- More than three continuously animated operational elements in one viewport.

### 13.4 Reduced motion

Settings offer `Follow system`, `Reduced`, and `Full` (default is `Follow system`). `prefers-reduced-motion: reduce` or the explicit Reduced setting:

- sets nonessential durations to 0–80 ms;
- replaces transforms with opacity or immediate state changes;
- stops scanlines, waveform loops, ambient pulses, and graph-edge flow;
- uses a deterministic static graph layout;
- changes map fly-to into immediate focus;
- preserves progress values, selection, hierarchy, and every control.

Reduced motion is a first-class screenshot/test state, not a late CSS override.

## 14. Empty, loading, failure, and blocked patterns

### Empty

- State the scope: “No findings in this review queue,” not “No exposure exists.”
- Explain whether nothing has run, filters hide content, or a completed check returned no findings.
- Offer one safe primary action and an optional clear-filter action.
- Use a small route/thread diagram or icon, not a stock illustration.

### Loading

- Skeletons match final structure and do not display plausible fake values.
- Preserve prior data during refresh and mark it stale where appropriate.
- Announce the region as busy and provide a restrained textual label.
- Use indeterminate progress only when the amount of work is unknowable.

### Failure

- Name the failed operation, preserve completed work, show a stable generic error code, and offer retry/details/manual fallback as applicable.
- Do not expose raw exceptions, file paths, tokens, or sensitive values in the default surface.
- Rose is limited to the failed region and action consequence, not the entire screen.

### Blocked/manual action

- Amber leads, with a boundary icon and plain reason.
- Explain what was and was not checked.
- Offer guided browser capture, local file import, skip provider, or return-to-plan as lawful alternatives.
- Never suggest evasion, CAPTCHA bypass, credential testing, or access-control circumvention.

### Restricted/quarantined

- Show the category and source segment, never the complete detected value.
- Explain that the value cannot be searched, logged, prompted, or transmitted.
- Allow removal of the source segment and access to safe-handling guidance.

## 15. Accessibility implementation requirements

- Meet WCAG 2.2 AA, including visible focus, target size/spacing, error association, status messages, and reflow.
- Respect macOS Full Keyboard Access, VoiceOver, Increase Contrast, Reduce Transparency, and Reduce Motion.
- Use semantic HTML first; Radix primitives provide behavior but do not waive labeling and keyboard review.
- Keep DOM/source order aligned with visual order at every breakpoint.
- Give each route a unique title and one `h1`; announce route changes and restore meaningful focus.
- Provide skip navigation and avoid keyboard traps.
- Do not use tooltips for essential content. Tooltips open on focus and hover and can be dismissed.
- Tables have captions or accessible names, header associations, and sort state.
- Charts expose data; graph and map expose synchronised non-visual alternatives.
- Live regions are throttled. Logs and counters do not flood announcements.
- Error summaries link to fields; field state is not color-only.
- Sensitive reveal controls announce hidden/revealed state without reading the hidden value automatically.
- Validate at 200% zoom and at the 1100 × 800 compact-laptop viewport.
- Test dark theme under common color-vision simulations; semantic icons and text remain sufficient regardless of color perception.

## 16. Privacy-by-design presentation

- The title bar carries a persistent **Synthetic data** marker throughout Phase 1.
- Screenshots use generic labels, opaque IDs, coarse locations, masked sensitive values, and `.invalid` hosts.
- Sensitive values are masked by default in rows, logs, ledgers, previews, notifications, and export review.
- Copy actions are explicit, named, and never attached to a whole row by accident.
- Clipboard success messages name the field category, not its value.
- Lock state removes sensitive DOM content rather than merely blurring it visually.
- Filter/search input is local and is never mirrored into a route if it may contain an identifier.
- External-link icons and transmission controls are visually distinct from local navigation.
- Full export is secondary and warned; redacted export is primary.
- No telemetry, remote font, remote icon, stock image, or analytics pixel is part of the design system.

## 17. Implementation conventions

### 17.1 Component state contract

Every interactive component documents and tests:

```text
default
hover (where supported)
active/pressed
focus-visible
selected/current
disabled with reason
loading/busy
validation error
high contrast
reduced motion
long content / 200% zoom
```

### 17.2 CSS and theming

- Store foundational and semantic tokens in layered CSS files; component styles consume only semantics.
- Use logical properties for layout and spacing.
- Use CSS Modules or locally scoped styles; global styles are limited to reset, tokens, typography, focus, and shell foundations.
- Use container queries for reusable panels and viewport queries for the application shell.
- Avoid runtime-generated arbitrary color values. Graph/category palettes are named and tested.
- Respect safe-area insets and title-bar drag/no-drag regions in Tauri.

### 17.3 Component ownership

Components live in the desktop application until a second real consumer exists. Token definitions and primitive contracts may move into `packages/design-system`; feature-specific panels remain with their feature.

Suggested layers:

```text
tokens → primitives → patterns → feature compositions → route screens
```

Primitives do not know audit/provider domain objects. Patterns such as `StatusBadge`, `TransmissionPreflight`, and `EvidenceArtifact` may know controlled domain vocabularies. Route screens own data assembly.

## 18. Visual QA and screenshot gate

Every major route and representative state is captured at:

- 1728 × 1117 (wide);
- 1440 × 900 (standard);
- 1100 × 800 (compact laptop).

The review checks:

1. One clear focal point and correct safety/action hierarchy.
2. Consistent shell, grid, spacing, baseline, and alignment.
3. Legible type at real pixel size; no essential text below the token floor.
4. Contrast, visible focus, keyboard order, and VoiceOver naming.
5. Long IDs, URLs, filenames, badges, translations, and dense results.
6. Loading, empty, degraded, failure, blocked/manual, restricted, and locked states.
7. Table column priority and absence of page-level horizontal overflow.
8. Graph label density, selected-edge explanation, and alternative table.
9. Coarse private-location handling and map failure fallback.
10. Motion smoothness and complete reduced-motion rendering.
11. Simulated/synthetic marker visibility and absence of misleading live language.
12. No real personal data, private-reference material, secrets, exact private locations, or unintended plaintext in the image.

After review, defects are recorded in `SCREENSHOT_REVIEW.md`, fixed, and recaptured. A route is not visually complete merely because it renders.

## 19. Design-system exit criteria

Phase 1 may pass the design-system gate only when:

- all tokens and core components are represented in `/states`;
- every canonical screen uses the same shell, spacing, type, focus, status, and motion contracts;
- all required component states exist and are interaction-tested;
- source outcome, attribution, confidence, sensitivity, provenance, and time remain visually independent;
- synthetic workflows remain visibly simulated and make no external requests;
- the three-viewport screenshot matrix has been reviewed, corrected, and recaptured;
- keyboard-only, VoiceOver, 200% zoom, Increase Contrast, Reduce Transparency, and reduced-motion checks pass or residual defects are explicitly documented;
- privacy scanning and screenshot review find no confidential or real identity data.
