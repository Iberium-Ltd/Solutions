# Decision Register

Last updated: 2026-07-11

This register records concise project-level decisions. Detailed architecture trade-offs live in [ADR-001](docs/architecture/ADR-001-technology-stack.md); later irreversible decisions require their own ADR.

| ID | Status | Decision | Reason and consequence |
|---|---|---|---|
| D-001 | Accepted | Build the complete high-fidelity interface before the production backend. | The interaction, privacy, evidence, uncertainty, and responsive model must be reviewed before service contracts harden. Backend implementation remains gated on Phase 1 test and screenshot evidence. |
| D-002 | Accepted | Use Tauri 2 with React, strict TypeScript, and Vite; add a Python core sidecar only in Phase 2. | This gives a compact macOS shell and mature UI tooling while preserving Python for later parsing, evidence, and local-ML workloads. See ADR-001. |
| D-003 | Accepted | Permit synthetic development data only and reserve `.invalid` hosts for illustrative network-shaped values. | Confidential references are methodology inputs only. They are ignored, never packaged, and never copied into source, fixtures, tests, screenshots, documentation, or Git history. |
| D-004 | Accepted | Model Phase 1 activity as deterministic, labelled, in-memory simulation with no external requests. | Screens and interactions can be tested reproducibly without implying provider coverage or exposing identifiers. Simulation state must never masquerade as production execution. |
| D-005 | Accepted | Deny external transmission by default and keep provider access outside the webview. | Future traffic must pass typed core adapters, policy checks, a disclosure preflight, budgets, and an audit ledger. Phase 1 contains no provider access. |
| D-006 | Accepted | Keep graph data library-neutral while using Cytoscape.js for the Phase 1 view. | Preset positions make screenshots deterministic. Production persistence will use a relational graph abstraction unless measured scale justifies a dedicated graph database. |
| D-007 | Accepted | Use a local schematic geographic view for Phase 1 and coarse private locations by default. | The prototype needs no tile or geocoding network boundary. A production MapLibre dependency is deferred until real, policy-governed geographic data exists. |
| D-008 | Accepted | Package fonts, icons, and visual assets locally and keep telemetry off. | The interface remains usable offline and visual tests do not depend on remote CDNs or analytics. |
| D-009 | Accepted | Use semantic design tokens, accessible native/Radix controls, explicit focus handling, and reduced-motion support. | Dense intelligence-console presentation must remain keyboard-operable and WCAG-oriented; color and animation cannot be the sole carriers of meaning. |
| D-010 | Accepted | Fail closed in repository and visual-test privacy checks. | Confidential paths, likely secrets, non-reserved demo email addresses, unexpected external requests, and unreviewed generated artifacts block sharing or test approval. |
| D-011 | Accepted | Set a 10 px absolute typography floor, with essential prose, actions, status, and decision text at 11 px or larger. | Screenshot review showed that 7–9 px density harmed real-pixel legibility. Ten-pixel text is limited to auxiliary machine metadata with a complete adjacent or accessible representation. |
| D-012 | Accepted | Adopt ADR-002 for vault encryption, key hierarchy, lock/unlock behavior, backup, recovery, and native Keychain custody. | The accepted design keeps key material outside the webview and establishes a fail-closed local vault boundary. The completed Phase 2 foundation does not authorise real-data use before the Phase 9 release gates. |
| D-013 | Accepted | Adopt ADR-003 for authenticated UI-to-core IPC and its event protocol. | Tauri mediates typed commands, development uses authenticated loopback TCP, and packaged operation uses a Unix-domain socket. Authentication, replay, origin, lifecycle, and cleanup checks must remain release gates. |
| D-014 | Accepted | Adopt ADR-004 for durable task execution, concurrency, retry, and cancellation. | Durable jobs need explicit state transitions and recoverable semantics rather than UI-owned background work. The bounded synthetic Phase 2 implementation and recovery gate pass; operational handlers remain later-phase work. |
| D-015 | Accepted | Use the verified CommonCrypto SQLCipher 4.17.0 / SQLite 3.53.3 arm64 package and accept PyInstaller 6.21.0 one-file packaging for the current spike; defer Nuitka. | The clean spike produced a native arm64 executable with a macOS 11 minimum, constrained dynamic dependencies, and passing TCP/UDS security and cleanup checks. This is evidence for the packaging direction, not release approval. |
| D-016 | Accepted | Permit a dedicated local packaging-spike overlay to disable the hardened runtime only for ad-hoc bundle validation. | The first hardened ad-hoc bundle correctly failed when PyInstaller's extracted `libpython` had no Team ID matching the Tauri executable. Production keeps the hardened-runtime requirement: sign PyInstaller's embedded libraries and Tauri with the same Developer ID, then notarise and validate the package on a clean supported Mac. The overlay is not a release configuration or approval. |
| D-017 | Accepted | Use ADR-005's fixed FD-198 anonymous, one-operation binary lease for database create/unlock keys. | Rust independently authorises the canonical vault binding and defers Keychain access until `REQUEST`; Python stages SQLCipher and publishes only between `COMMIT` and `COMMITTED`. Keys never enter HTTP, argv, environment, logs, files, or the webview, and lock replaces the sidecar/channel. |

## Pending decisions

- Release decision: arm64-only versus universal macOS distribution.
- Completion evidence for same-Developer-ID nested signing, hardened runtime,
  notarisation, clean-machine validation, and final distribution approval.
