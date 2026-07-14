# Codename Ariadne — Phase 1 Screenshot Review

Last updated: 2026-07-12  
Current status: **Complete**  
Approval state: **Approved — Phase 1 UI gate passed; later backend work does not reopen the accepted baseline**

## Scope and safety

This review covers the complete Phase 1 visual contract in
`docs/ui/visual-test-matrix.md`: 17 major routes and 6 representative states at
1440 × 900, 1728 × 1117, and 1100 × 800. All captures use deterministic
synthetic fixtures, a frozen application clock, local assets, blocked external
network requests, and reserved `.invalid` domains. No confidential reference
identity or imported user material is present in the reviewed artifacts.

## Capture history

| Pass | Result | Evidence and disposition |
|---|---:|---|
| `pass-01` | **63 / 69 captured** | Capture stopped before S05/S06 because the reduced-motion fixture exposed a precedence defect. The incomplete pass was retained and was never presented as successful. |
| Reduced-motion probe | **Passed** | Motion precedence was corrected so the explicit fixture remains authoritative while the system and in-app preference paths continue to work. |
| `pass-01b` | **69 / 69 captured** | Complete baseline set. All 69 PNGs were manually reviewed at original resolution across the three viewports. The review found no privacy or route failures, but it identified the visual and accessibility defects recorded below; the pass was not approved. |
| `pass-02` | **69 / 69 captured** | Complete post-remediation set. A second full manual review confirmed the broad baseline fixes, then found residual compact-viewport issues around M10 hash/action visibility, S02 and S04 callout visibility, and M17 state-canvas height. The pass was rejected pending focused fixes. |
| `pass-02b` | **69 / 69 captured and accepted** | Final set. The manifest reports `captureSetComplete: true`, Chromium 149.0.7827.55, fixture version `ariadne-visual-v1`, frozen clock `2034-06-15T12:00:00.000Z`, and `reviewStatus: accepted`. Every automated route, viewport, overflow, privacy, state-proof, reduced-motion, and capture-integrity assertion passed. |

## Review method for the final pass

`pass-01b` and `pass-02` were each reviewed manually in full at original
resolution. Because the changes after `pass-02` were narrow and already covered
by the full automated 69-image contract, `pass-02b` used targeted visual checks
instead of a third redundant manual review of unchanged screens.

The final M03, M05, M10, S02, and S04 artifacts were verified byte-for-byte
against the already inspected, passing focused probes. M17 was inspected at the
affected wide viewport after its height correction. The complete `pass-02b`
suite independently revalidated all 69 route/viewport combinations, including
the required proof-in-viewport assertions. This provides final-change coverage
without repeatedly loading unchanged images.

## Final severity

| Severity | Count | Disposition |
|---|---:|---|
| Critical | **0** | No privacy leak, confidential value, unsafe automatic action, broken route, or bypassed primary journey was found. |
| Major | **0** | All blocking visual, responsive, accessibility, and action-hierarchy findings were corrected and recaptured. |
| Minor | **3 accepted tradeoffs** | Documented below; none obscures required information, blocks an action, causes overflow, or weakens the product's safety model. |

## Resolved findings

- **Typography:** the stale baseline assumption of a universal 12 px minimum
  was replaced by the tested design-system rule in D-011: explicit CSS sizes
  have a 10 px hard floor, while essential prose, actions, and status text are
  11 px or larger. An automated typography test enforces the floor.
- **Initial-viewport proof:** compact M02, M03, M05, and M06 workflow controls
  now use sticky, in-flow action bars rather than fixed overlays. Required
  actions and recovery guidance remain visible without concealing content.
- **Clipping and truncation:** the M04 edit control, M07 outcome,
  M08 legend, M10 hash, M11 assessment badge, and M13 selected-case treatment
  were corrected. M10 exposes the complete hash in a labelled, focusable region
  and keeps its copy action visible.
- **Safety hierarchy:** M15 no longer presents a policy exception as the
  visually recommended path; the deliberate exception and safe default are
  clearly differentiated.
- **Compact-shell accessibility:** the New Audit link retains an accessible
  name when its visible label is collapsed. Compact accessible-name coverage
  passes in both browser engines.
- **Representative states:** S01, S03, S05, and S06 now keep their required
  candid explanation, recovery, table, hash, and action proof in the initial
  compact viewport. S02 and S04 were compacted so their assurance and boundary
  callouts are fully visible.
- **State-canvas spacing:** the excessive M17 minimum height was removed. Its
  wide layout now follows content height instead of manufacturing empty panel
  space.
- **Capture integrity:** deterministic software-rendered Chromium capture,
  frozen time/randomness, local fonts, network blocking, readiness checks, and
  a post-ready quiet frame eliminate the incomplete-paint behavior observed in
  early rapid capture.

## Accepted minor tradeoffs

- Wide state-selector helper descriptions may ellipsize, while every state name
  remains complete and unambiguous.
- The wide state-laboratory page is naturally top-heavy after removal of the
  artificial canvas minimum height; the unused page canvas is not a component
  defect.
- On compact M13, the inspector follows the primary case list below the initial
  viewport by design. The route remains usable, ordered, and free of concealed
  controls or document-level horizontal overflow.

## Final route and state disposition

All M01–M17 routes and S01–S06 representative states passed at 1440 × 900,
1728 × 1117, and 1100 × 800. The final contract contains 51 major-route images
and 18 state images, for 69 accepted captures in total. No screenshot contains
confidential data, a real personal identifier, or document-level horizontal
overflow.

Phase 1's UI-first gate is approved. This approval covers the scaffolded,
synthetic-data interface and its visual behavior only; it does not claim that
the full backend, real evidence pipeline, provider integrations, or production
security controls have been implemented.

## Phase 3 disposition

Phase 3 connected native Intake and Entities routes without redesigning the accepted visual system. Per the agreed review strategy, the 69-image matrix was not loaded and manually reviewed again. Two targeted 1440×900 captures covered the changed major screens. Intake was visually sound; the first Entities capture occurred before paint completed, so it was re-captured once after a short delay and rendered correctly with no visual defect requiring a code change. Automated frontend coverage finished at 41/41 tests across 12 files, including lock-time sensitive DOM clearing. A new full visual pass is required only if later work materially changes layout or exposes a defect.

## Current 45-operation candidate disposition

The historical Phase 1 and Phase 3 reviews above have not been reopened or represented as evidence for the newest screens. A targeted Playwright pass captured four changed major screens at 1440×900:

- Workspace AI
- Corpus AI
- Public Discovery
- Entity exact-origin pagination

Fresh-context Playwright capture passed **4/4** for Public Discovery, Workspace AI, Corpus AI, and Entity Review/exact origins. The initially scrolled entity-origin capture worked but framed the screen poorly; a focused top-of-page recapture plus a separate panel detail passed **1/1** without requiring an application code change. Public Discovery, Workspace AI, the corrected Entity capture, and the exact-provenance panel were manually inspected, and no blocking defect remained.

Five artifacts are retained under `apps/desktop/artifacts/ui-screenshots/final-targeted-20260713-01`: the four 1440×900 major-screen captures plus one focused exact-origin panel detail. The accepted 69-image matrix was not reopened and will not be manually reviewed again unless a later test identifies a shared layout regression. The current targeted visual gate is **passed**.
