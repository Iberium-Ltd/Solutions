# Phase 1 Visual Test Matrix

Status: Screenshot contract for the UI-first quality gate  
Target: Playwright Chromium, viewport screenshots, synthetic fixtures only

## Purpose and gate

This manifest defines the screenshots required before Codename Ariadne may begin full backend implementation. It covers every Phase 1 functional route, the shared application shell and navigation, the three required viewport sizes, and representative non-happy-path states.

A route is not visually approved merely because a screenshot exists. Its screenshot must be reviewed against the criteria in this document, defects must be corrected, and a clean recapture must pass. The approved set contains:

- 17 major routes at 3 viewports: **51 screenshots**.
- 6 representative state variants at 3 viewports: **18 screenshots**.
- **69 screenshots total per review pass**.

The application shell and primary navigation are persistent. They are therefore reviewed in all 51 major-route captures rather than represented by a separate, artificial shell-only screen. `/` redirects to `/dashboard` and is a route-smoke assertion, not a separate screenshot.

## Viewport contract

| Key | Viewport | Device scale factor | Intent |
|---|---:|---:|---|
| `desktop` | 1440 × 900 | 1 | Primary desktop workspace |
| `wide` | 1728 × 1117 | 1 | Large Mac display and high-density layouts |
| `narrow` | 1100 × 800 | 1 | Narrow laptop width; compact navigation and overflow pressure |

All captures are viewport screenshots with browser chrome excluded and `fullPage: false`. A page must fit its intended workspace; scrolling regions may scroll internally, but the document must not acquire accidental horizontal scrolling.

## Synthetic fixture contract

Visual fixtures must be local, deterministic, and visibly marked as synthetic where that prevents confusion. Fixture values must use generic labels and reserved domains, for example:

- Profile: `Synthetic Profile 001`
- Email: `user_0001@example.invalid`
- Username: `synthetic_handle_0001`
- Organisation: `Example Systems 001`
- Location: `Example Region 001`
- Run ID: `run-syn-0007`
- Finding ID: `finding-syn-0014`
- Case ID: `case-syn-0003`

No fixture may be derived from, resemble, or quote a confidential reference identity. Exact private addresses, real domains, credentials, tokens, live URLs, real provider responses, and imported user material are prohibited in screenshot fixtures. Development fixture query parameters must be enabled only in test/development builds and must not activate fixture data in a packaged release.

## Major-route manifest

Each row is required at all three viewports. The query string freezes the named local fixture and enables capture stabilization.

| ID | Exact route and fixture | Required visible proof | 1440 × 900 artifact | 1728 × 1117 artifact | 1100 × 800 artifact |
|---|---|---|---|---|---|
| M01 | `/dashboard?fixture=standard&capture=1` | Mission control, current synthetic run, coverage limitations, alerts, next actions, active Dashboard navigation | `M01-dashboard__1440x900.png` | `M01-dashboard__1728x1117.png` | `M01-dashboard__1100x800.png` |
| M02 | `/audits/new?fixture=full-audit-draft&capture=1` | New-audit stepper, audit type, scope, profile choice, permissions and budget summary | `M02-new-audit__1440x900.png` | `M02-new-audit__1728x1117.png` | `M02-new-audit__1100x800.png` |
| M03 | `/audits/new/intake?fixture=pasted-source&capture=1` | Paste and file intake, supported file types, local-processing notice, validation/quarantine feedback | `M03-intake__1440x900.png` | `M03-intake__1728x1117.png` | `M03-intake__1100x800.png` |
| M04 | `/audits/new/entities?fixture=review-mixed&capture=1` | Extracted entities, edit/classify/approve/exclude controls, sensitivity, history and transmission decisions | `M04-entity-review__1440x900.png` | `M04-entity-review__1728x1117.png` | `M04-entity-review__1100x800.png` |
| M05 | `/tools?fixture=standard&capture=1` | Complete named tool launcher, search/filtering, capability summary, jurisdiction/transmission risk cues | `M05-tool-launcher__1440x900.png` | `M05-tool-launcher__1728x1117.png` | `M05-tool-launcher__1100x800.png` |
| M06 | `/operations/run-syn-0007?fixture=active&capture=1` | Clearly labelled Phase 1 simulation, progress, workers, queue, provider states, cost, findings and safe run controls | `M06-live-operations__1440x900.png` | `M06-live-operations__1728x1117.png` | `M06-live-operations__1100x800.png` |
| M07 | `/findings?fixture=review-queue&capture=1` | Findings inbox with independent outcome, visibility, attribution, confidence, sensitivity, provenance and review states | `M07-findings__1440x900.png` | `M07-findings__1728x1117.png` | `M07-findings__1100x800.png` |
| M08 | `/graph?fixture=identity-standard&capture=1` | Legible identity/provenance graph, filters, private-node control, focus, edge explanation and evidence affordance | `M08-identity-graph__1440x900.png` | `M08-identity-graph__1728x1117.png` | `M08-identity-graph__1100x800.png` |
| M09 | `/map?fixture=coarse-locations&capture=1` | Coarse private locations, current/historic distinction, source/confidence context, time and jurisdiction controls | `M09-geographic-map__1440x900.png` | `M09-geographic-map__1728x1117.png` | `M09-geographic-map__1100x800.png` |
| M10 | `/findings/finding-syn-0014?fixture=evidence-rich&capture=1` | Result detail, source and capture metadata, hash, immutable evidence, positive/negative signals and missing evidence | `M10-result-evidence__1440x900.png` | `M10-result-evidence__1728x1117.png` | `M10-result-evidence__1100x800.png` |
| M11 | `/cases/impersonation/case-syn-0003?fixture=unresolved&capture=1` | Careful classification language, timeline, ownership periods, contradictions, evidence gaps and draft-only reporting | `M11-impersonation-case__1440x900.png` | `M11-impersonation-case__1728x1117.png` | `M11-impersonation-case__1100x800.png` |
| M12 | `/compare?fixture=two-runs&capture=1` | Run selectors and distinct NEW, CHANGED, REMOVED, REAPPEARED, archived and unknown states | `M12-compare-runs__1440x900.png` | `M12-compare-runs__1728x1117.png` | `M12-compare-runs__1100x800.png` |
| M13 | `/remediation?fixture=active-cases&capture=1` | Removal Tracker board, status, owner, due date, evidence, provider response, recheck and reappearance | `M13-remediation__1440x900.png` | `M13-remediation__1728x1117.png` | `M13-remediation__1100x800.png` |
| M14 | `/providers?fixture=global-registry&capture=1` | Source Radar health, operator/hosting jurisdiction, access basis, retention, terms, risk and enable state | `M14-provider-registry__1440x900.png` | `M14-provider-registry__1728x1117.png` | `M14-provider-registry__1100x800.png` |
| M15 | `/privacy/transmission?fixture=preflight&capture=1` | Local/EU/world/custom modes and preflight provider, purpose, payload masking, retention, cost, risk and approval | `M15-transmission-controls__1440x900.png` | `M15-transmission-controls__1728x1117.png` | `M15-transmission-controls__1100x800.png` |
| M16 | `/settings/privacy?fixture=standard&capture=1` | Manual vault session, retention, redaction, local AI, connector, telemetry-default-off and motion controls | `M16-settings-privacy__1440x900.png` | `M16-settings-privacy__1728x1117.png` | `M16-settings-privacy__1100x800.png` |
| M17 | `/states?case=overview&capture=1` | State laboratory overview with state semantics, status labels, actions and accessibility annotations | `M17-state-lab__1440x900.png` | `M17-state-lab__1728x1117.png` | `M17-state-lab__1100x800.png` |

## Representative-state manifest

These captures use explicit frozen cases on `/states`; no screenshot waits for a transient network or timer condition. Each row is required at all three viewports.

| ID | Exact route and environment | Required visible proof | 1440 × 900 artifact | 1728 × 1117 artifact | 1100 × 800 artifact |
|---|---|---|---|---|---|
| S01 | `/states?case=empty&capture=1` | Empty findings/remediation examples explain why they are empty, avoid claiming nonexistence, and offer a safe next action | `S01-empty__1440x900.png` | `S01-empty__1728x1117.png` | `S01-empty__1100x800.png` |
| S02 | `/states?case=loading&capture=1` | Stable skeleton/progress examples reserve final layout space, use meaningful labels and expose a busy state without flicker | `S02-loading__1440x900.png` | `S02-loading__1728x1117.png` | `S02-loading__1100x800.png` |
| S03 | `/states?case=failure&capture=1` | `CHECK_FAILED`, `RATE_LIMITED`, and `PROVIDER_UNAVAILABLE` remain distinct; cause, retained progress and bounded retry action are visible | `S03-failure__1440x900.png` | `S03-failure__1728x1117.png` | `S03-failure__1100x800.png` |
| S04 | `/states?case=blocked&capture=1` | `ACCESS_BLOCKED` and manual-action request are explicit; guided capture/import is offered without bypass or completeness claims | `S04-blocked-manual__1440x900.png` | `S04-blocked-manual__1728x1117.png` | `S04-blocked-manual__1100x800.png` |
| S05 | `/states?case=reduced-motion&capture=1`; `reducedMotion: reduce`; app preference `system` | Graph/scan/progress content remains understandable with nonessential motion removed and no hidden state or blank visual | `S05-reduced-motion__1440x900.png` | `S05-reduced-motion__1728x1117.png` | `S05-reduced-motion__1100x800.png` |
| S06 | `/states?case=long-identifier&capture=1` | Long URL, hash, provider label and identifier wrap, truncate with disclosure, or scroll only within their component; actions remain reachable | `S06-long-identifier__1440x900.png` | `S06-long-identifier__1728x1117.png` | `S06-long-identifier__1100x800.png` |

The S06 fixture must include these generic stress values so the result is reproducible:

```text
finding_syn_0000000000000000000000000000000000000000000000000000000000000000000000000000000000000001
https://profile.example.invalid/synthetic-segment-0001/synthetic-segment-0002/synthetic-segment-0003/synthetic-segment-0004
sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
Synthetic Provider With A Deliberately Long Descriptive Display Name For Layout Testing
```

Truncation must never remove the ability to copy or reveal the complete synthetic value. Hashes, URLs and immutable IDs must not be visually rewritten as different values.

## Deterministic capture protocol

### Runtime

1. Build or serve the same production-mode UI bundle used for route testing. Use one documented local origin for the whole pass, such as `http://127.0.0.1:4173`.
2. Use the repository-pinned Playwright and bundled Chromium versions. Run captures with one worker so animation clocks and fixture state cannot race.
3. Deny external network traffic. Permit only the local application origin and local static assets. A network request to any other origin fails the test.
4. Start each screenshot in a fresh browser context with cleared cookies, storage, caches and service workers.
5. Set locale to `en-GB`, timezone to `UTC`, colour scheme to `dark`, device scale factor to `1`, and browser zoom to `100%`.
6. Install or bundle fonts locally. Do not depend on a remote font CDN or host font substitution.
7. Freeze the application clock at `2034-06-15T12:00:00.000Z`, seed pseudo-random layout with `ariadne-visual-v1`, and use only the fixture named in the route.

### Page readiness

For every route and viewport:

1. Navigate directly to the exact pathname and query in this manifest.
2. Assert the expected route heading and active navigation item; a fallback, redirect loop, error boundary or 404 fails capture.
3. Await `document.fonts.ready`.
4. Await the route root `[data-testid="route-ready"]` and `document.documentElement.dataset.captureReady === "true"`.
5. For graph/map routes, await the explicit layout-settled signal. Do not use an arbitrary sleep as a substitute.
6. Assert that no unexpected console error, unhandled rejection, failed local asset, or external request occurred.
7. Move the pointer to the neutral bottom-right corner, blur text inputs, hide the text caret, and reset all intended scroll containers to their fixture-defined positions.
8. Apply the capture stabilizer only after readiness: pause decorative animation, suppress caret blinking and fix transient progress at its fixture value. Do not use it to hide overflow, loading defects or content.
9. Capture PNG at the viewport size with `animations: "disabled"`, `fullPage: false`, and an opaque background.

Loading is frozen by S02 fixture state, so disabling animation must leave a visible, meaningful loading representation. For S05, set `page.emulateMedia({ reducedMotion: "reduce" })` before navigation. Separately test the explicit in-app reduced-motion override with OS preference set to `no-preference`; the screenshot proves the representative appearance while the interaction test proves both control paths.

### Artifact retention

Store captures under the ignored path:

```text
artifacts/ui-screenshots/
├── pass-01/
│   ├── major/
│   └── states/
└── pass-02/
    ├── major/
    └── states/
```

Never overwrite a reviewed failing pass. The manifest filename remains unchanged inside its pass directory. Record browser version, commit/worktree identifier, capture command, clock, fixture version and viewport in a machine-readable manifest beside the images. The PNGs, capture metadata and any diffs remain ignored and must pass the screenshot privacy/OCR check before being shared.

## Assertions paired with screenshots

Pixels alone are insufficient. Each route capture must be paired with automated assertions for:

- one visible `h1`, the correct document title, landmark structure and active navigation state;
- no horizontal document overflow (`scrollWidth <= clientWidth`) at all three viewports;
- no clipped primary action, inaccessible modal/drawer, or content hidden behind persistent chrome;
- visible keyboard focus for the route's primary action and a logical tab sequence in a separate interaction test;
- accessible names for icon-only controls and text alternatives or labels for non-text status information;
- status meaning conveyed by text/icon as well as colour;
- independent display of check outcome, visibility, attribution, confidence, sensitivity and provenance where applicable;
- no exact private-coordinate presentation and no real or non-reserved identity data;
- no automatic-send wording or enabled automatic submission action;
- no false completeness claim when data is empty, failed, unavailable or blocked;
- the explicit Phase 1 simulation label anywhere simulated run data appears.

## Critical visual review rubric

Review every image at 100% scale and compare the three viewports side by side. Do not approve by looking only at pixel-diff percentages.

| Area | Questions that must be answered |
|---|---|
| Structure and alignment | Do shell rails, headers, panels, tables and graph controls share deliberate anchors? Are there stray one-pixel offsets, collapsed columns or unintended gaps? |
| Spacing and density | Is information dense but scannable? Are related controls grouped, repeated spacing tokens consistent and click targets sufficiently separated? |
| Typography | Are hierarchy, line length, line height and numeric alignment clear? Is any label too small, excessively letter-spaced, clipped or ambiguously truncated? |
| Contrast and colour | Are text, focus rings, dividers, charts and status badges legible? Does restrained neon preserve accessible contrast without glow obscuring glyphs? |
| Responsive behaviour | At 1100 × 800, does navigation compact intentionally, do panels reflow in the correct order, and are primary actions still visible without document-level horizontal scroll? |
| Overflow and stress text | Do long IDs, hashes, URLs, provider names, error messages and translated-length labels remain contained and inspectable? Do tables offer intentional component scrolling? |
| State honesty | Are empty, loading, failure and blocked states visually distinct and candid? Are partial results retained? Is failure never presented as absence? |
| Safety and privacy | Are all identities synthetic, locations coarse, transmission warnings prominent and dangerous/irreversible actions explicit? Is there any accidental imported data or live URL? |
| Provenance and uncertainty | Can the user identify source, capture time, evidence, contradictions and confidence without treating a score as proof? Are independent evidence dimensions kept separate? |
| Graph and map readability | Are node/edge labels and selected states legible, overlaps controlled, controls discoverable, private nodes/locations protected and evidence reachable? |
| Interaction chrome | Are hover-independent meanings visible, focus states not clipped, disabled controls distinguishable and drawers/tooltips within the viewport? |
| Motion | With normal motion, are transitions purposeful and free of flicker/jank in trace/video review? With reduced motion, is nonessential motion removed without losing progress or graph meaning? |
| Visual integrity | Are there broken icons, fallback fonts, blurry canvas/SVG output, mismatched radii, inconsistent shadows, accidental transparent seams or fake/unlabelled charts? |

## Severity and approval

- **Critical:** privacy leak, confidential/reference-derived value, unsafe action, inaccessible primary journey, broken route, unreadable core content, or misleading absence/completeness claim. Stop capture, remove the artifact from any shared location, fix, and rerun privacy checks.
- **Major:** clipped/overlapping content, document overflow, missing provenance or state meaning, low contrast, unusable graph/map, hidden primary action, inconsistent responsive layout, or failure at one required viewport. Fix before approval.
- **Minor:** local polish defect that does not alter meaning or block use, such as a small token inconsistency. Fix in the current pass or record an owner and explicit rationale in `SCREENSHOT_REVIEW.md`.

Approval requires all 69 current-pass artifacts, passing paired assertions, zero open Critical or Major defects, documented disposition of every Minor defect, a clean screenshot privacy/OCR review, and a written route-by-route review in `SCREENSHOT_REVIEW.md`. After any shared component, design token, font, shell, fixture or viewport-behaviour change, recapture every affected route at all three sizes; when impact is uncertain, recapture the complete set.
