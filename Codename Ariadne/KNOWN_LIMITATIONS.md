# Known Limitations

Last updated: 2026-07-14  
Applies to: completed Phase 0–3 gates, the 48-operation local candidate, and every separately identified historical package

Codename Ariadne is not release-ready. Phase 3 remains historically verified through `0005_graph_edge_origins`; preserved `0006_query_policy_core`, `0007_phase5_evidence_attribution`, and 37-/40-/45-operation `0008_phase6_audit_remediation` packages each retain separately identified local evidence. The current 48-operation candidate completed its full aggregate/frozen/package gate under new identities, and no earlier artifact is relabelled as its evidence. This is local ad-hoc proof, not production signing, notarisation, clean-machine, or release approval.

## Functional limitations

- Native Intake, Entities, Graph, Settings/local-AI, Transmission/query, Findings, Compare, and Removal Tracker slices now use narrow local-core boundaries. Browser mode and most broader audit screens remain deterministic simulations.
- React keeps only opaque profile/source IDs in a non-persistent memory store. Reloading loses the active selection, but vault profile listing and the native profile switcher now let the user select an existing active/draft profile again. Profile selection is not persisted and lock clears it.
- Native Graph is connected to persisted snapshots/provenance and passes the current synthetic candidate gate, but it is a bounded personal graph view rather than production-scale analytics or a production data boundary.
- File intake supports one non-empty TXT, Markdown, CSV, JSON, or vCard file up to 1 MiB. Archives, PDFs, Office/OLE files, images, binary formats, non-UTF-8 text, and bulk/streaming intake are deliberately rejected.
- Deterministic semantic enrichment is conservative and can miss aliases or relationships. Selectable local corpus/workspace AI can reason over broader context, but its summaries, connections, and gaps can still be incomplete or wrong and never establish ownership by themselves.
- The disabled-by-default AI vertical supports explicit loopback Ollama/OpenAI-compatible runtimes and optional OpenAI Responses. Intake, corpus, and workspace outputs are review-only; exact citations, bounded projections, strict structured output, and deterministic fallback reduce but do not eliminate model error. OpenAI Responses requires the user to provide a key for each request and sends selected bounded content to an external provider; it has automated coverage but no real paid-key live verification.
- Quarantine is metadata-only in Phase 3. Restricted values are redacted and not recoverable/releasable as ordinary entities; a future encrypted quarantine-object workflow requires a separate gate.
- Free-form entity-decision reasons persist only as keyed opaque codes. Human-readable reason history and its dedicated retention/export policy are deferred.
- Completed Phase 3 side effects replay for 24 hours. A response interrupted after reservation may remain ambiguous for up to 60 seconds, and webview retry keys are memory-only, so reload cannot automatically resume the same key.
- Phase 4 query planning still exposes only network-free local `DRY_RUN`/`MANUAL_LOCAL` providers. A separate explicitly authorised Discovery Console supports bounded DuckDuckGo HTML, unauthenticated GitHub-user search, official HIBP account/domain checks, deterministic multi-identifier planning, fixed manual portals, and a local advanced query composer. The composer shows its exact query and creates only user-opened browser handoffs for Google, Bing, DuckDuckGo, Brave, Ecosia, Startpage, and Mojeek; these are not integrated scrapers, and results/evidence are not imported automatically. The planner does not execute its steps. HIBP k-anonymity and verified-domain features depend on the user's provider plan/verification, direct email checks disclose the exact email only after separate authorization, and wider public providers plus authorised Gmail/GitHub account connectors do not exist. Discovery never bypasses login, CAPTCHA, paywalls, rate limits, verification, or other access controls.
- Phase 5 findings, immutable evidence originals/derivatives, multi-finding links, assessments, and append-only human decisions have durable profile-scoped SQLCipher repositories. Native Findings supports manual workflows, and Public Discovery can atomically retain one reviewed exact URL with its finding and neutral assessment. Operational assessment recalculation, evidence viewing/streaming, retention/purge, and broader adapter-produced findings remain unavailable.
- Manual evidence import checks the selected suffix/media declaration, canonical encoding, size, and schema but does not yet sniff file signatures or malware-scan HTML/PDF/image bytes. Originals remain sealed and are never actively rendered; a future viewer needs independent hostile-content inspection and sandboxing.
- Phase 6 snapshots, coverage, selected-run comparisons, and remediation revisions/history are durable and profile-scoped. Compare can automatically materialise current contentless Phase 5 state after a user gesture, but no adapter or scheduler creates checkpoints in the background and declared provider coverage is still manual.
- Reports generates one bounded JSON or Markdown artifact in memory for a selected snapshot pair. Redacted mode is default; full mode requires a new request-bound approval UUID and can reveal sensitive finding/remediation text. The core does not persist the report, approval, or artifact, choose a destination, or write a file. The UI's Blob download enters a user-chosen path outside app retention control. PDF/CSV/HTML, durable templates/approval expiry, destination brokering, report purge, and release-grade export review remain unavailable.
- No provider-contact/send/submit/dispatch operation exists. Remediation copy and drafts are not legal advice.

## Security and privacy limitations

- Browser-selected intake and Phase 5 evidence/derivative file bytes are read into WKWebView memory, base64-encoded, and sent through typed Tauri commands. Intake is capped at 1 MiB and evidence at 10 MiB; bounds/encoding are revalidated, persisted evidence receives a core-computed SHA-256, and no arbitrary path is exposed. Transient raw and base64 copies broaden the webview memory boundary, so an opaque native file-broker handle is preferred before real-data use.
- SQLCipher and migrations through `0005_graph_edge_origins` pass the historical Phase 3 frozen/package gates. `0006_query_policy_core`, `0007_phase5_evidence_attribution`, and the historical 37-/40-/45-operation `0008` builds separately retain their aggregate, frozen UDS, and packaged-app milestones under distinct identities. The current 48-operation aggregate/frozen/package gate also passes under `5ca6b790…` staged, `4ba7fd0…` packaged-sidecar, and `ca68fdd4…` desktop identities. None is a penetration test or fuzzing certification.
- The parser worker has strict resource, descriptor, IPC, and network bounds, but is not a complete macOS sandbox against every file readable by the same user account.
- Same-user malware or an unlocked account can inspect process memory or displayed data. The application cannot defend against a fully compromised OS.
- Auto-lock remains fixed at 300 seconds in the native shell. Physical sleep/wake and the real platform Keychain prompt remain Phase 9 manual validation gates.
- The Keychain API cannot forcibly dismiss a prompt already visible. Lock revokes the operation and drops a later result before key grant.
- Database-key and backup-key rotation are not implemented. Independently versioned, crash-safe rotation is mandatory before real-data release.
- The frozen native arm64 sidecar and Tauri package are local ad-hoc proofs. Production requires one Developer ID across PyInstaller internals and Tauri, hardened runtime, notarisation/stapling, entitlements review, and a clean supported macOS 14 arm64 validation.
- No secure-deletion guarantee is made for APFS, SSD wear levelling, snapshots, caches, traces, or backups.
- The privacy scanner reduces accidental repository exposure; it is not complete DLP, secret scanning, or Git-history remediation.

## UI and validation limitations

- The accepted Phase 1 `pass-02b` matrix contains 69/69 synthetic screenshots with no open Critical or Major defect. The current 48-operation source passes 143/143 Vitest tests across 36 files plus typecheck/lint/build and a final 2/2 targeted Chromium gate. Only the changed query composer and one Settings presentation were inspected; no blocking defect was found. The historical 45-operation targeted gate remains separate, and the broad screenshot matrix will not be recaptured unless a later check reveals a shared regression.
- Native Graph uses a deterministic bounded Cytoscape layout over persisted data; it is not production-scale graph analytics.
- The geographic surface is a schematic local vector view, not a geocoder or authoritative map.
- macOS is the only target; the configured minimum window is 1000×700. Browser distribution and mobile are out of scope.
- Wide state-selector helper text may ellipsize while state names remain complete; the compact finding inspector begins below the initial viewport by design.

## Coverage language

An empty, blocked, failed, unavailable, or unindexed result never proves nonexistence. `NOT_FOUND` applies only to one defined check. Extraction and semantic relation candidates are not identity attribution; ownership remains a human decision supported by provenance, contradictions, time, and explicit confidence.
