# Codename Ariadne Desktop

The desktop workspace began as the accepted synthetic Phase 1 interface and now
includes native vault/profile lifecycle, confirmed profile deletion,
intake/review, persistent named-person audits, real frontier-derived progress,
seven bounded public discovery surfaces, cited selected-local-AI analysis,
reviewed exact-source promotion, findings/evidence decisions, comparison,
remediation, and local reports. Browser mode remains explicitly synthetic.
Credentialed specialist providers, authorised account connectors, scheduled
audit ingestion, and outbound remediation actions remain absent.

For the practical vault-to-report workflow, see the [desktop user guide](../../docs/user-guide.md).

Do not use real personal information in this workspace. Reusable fixtures belong in `packages/synthetic-data`, and every illustrative email or URL must use a reserved `.invalid` host.

## Stack

- React 19 and strict TypeScript
- Vite 8
- React Router, Zustand, TanStack Query, Radix primitives, and Lucide icons
- Cytoscape.js for the deterministic Link Map
- Vitest, Testing Library, Axe, and Playwright
- Tauri 2 shell with a typed authenticated core supervisor

The full stack decision is documented in [ADR-001](../../docs/architecture/ADR-001-technology-stack.md).

## Prerequisites

- Node.js 24 with Corepack
- The pinned pnpm version from the root `package.json`
- Rust stable and macOS development tools only when running the Tauri shell
- Playwright browsers for E2E and screenshot work

Install workspace dependencies from the repository root:

```sh
corepack pnpm install --frozen-lockfile
corepack pnpm --filter @ariadne/desktop exec playwright install chromium webkit
```

## Run locally

Browser development mode:

```sh
corepack pnpm dev
```

Open `http://127.0.0.1:1420`. The server deliberately binds only to loopback.

Tauri development mode:

```sh
export PATH="/opt/homebrew/opt/rustup/bin:$PATH"
corepack pnpm --filter @ariadne/desktop exec tauri dev
```

Homebrew installs Rustup keg-only on the target Mac, so its shim directory must
be present in `PATH`. To exercise the current debug sidecar seam first run
`scripts/bootstrap_core.sh` from the repository root. Debug Rust then launches
the uv-managed service over authenticated random loopback and validates its
capabilities handshake. Pages without a native workflow keep an explicit synthetic fallback.

Packaged Rust mode never starts the uv/Homebrew development service. The latest
verified local packaging spike is the current 57-operation/55-path PyInstaller
artifact at `0011_profile_purge`, staged as an ignored Tauri external binary.
The staged sidecar is 21,053,600 bytes with SHA-256
`dccaaa5d3c9a60b668ecd85cdd0d00a79c4b16aadd2c02995e43891478a9d7f5`.
After ad-hoc packaging, the arm64/minimum-macOS-11 sidecar is 21,053,584 bytes
with SHA-256
`74325b31abba5afb4f916051898c80431018cd4a0b8ae90a9f44f0183281d7b0`;
the arm64/minimum-macOS-14 desktop executable is 17,815,088 bytes with SHA-256
`716052aab25cb30f2784c876e27f17c8ae2664f8b6f688a1db8377a57e06399d`.
This remains a local ad-hoc packaging proof, not a signed/notarised release, and
no vault key enters the webview boundary. The historical 45-operation and
earlier identities remain preserved separately.

## Validate

Run from the repository root:

```sh
python3 scripts/privacy_check.py
corepack pnpm typecheck
corepack pnpm lint
corepack pnpm test
corepack pnpm test:e2e
corepack pnpm test:webkit
corepack pnpm build
```

Capture the deterministic visual matrix with:

```sh
SCREENSHOT_PASS=local-review corepack pnpm screenshots
```

The matrix covers 23 route/state cases at three required viewports, producing 69 screenshots. The accepted Phase 1 baseline is `pass-02b`; use a new pass label for later review work so that baseline evidence is not overwritten. Generated screenshots, traces, reports, coverage, and test results are ignored local artifacts. Record the disposition of any new capture set in the repository review documents.

The current targeted gate retained four 1440×900 major-screen captures and one focused exact-origin detail under `artifacts/ui-screenshots/final-targeted-20260713-01`. Fresh-context capture passed 4/4, the corrected entity-origin recapture passed 1/1, and manual review found no blocking defect. The historical 69-image baseline was not reopened.

Production routes are lazy-loaded, and the production build completes without a large-chunk warning. The visual harness uses deterministic local fixtures, blocks external requests, exercises reduced-motion and accessible-name contracts, and verifies that key state evidence remains visible at compact viewports.

At the current 57-operation source head, frontend typecheck, lint, production
build, and 152/152 Vitest tests across 38 files pass. The primary native journey
now runs from explicit named-profile selection through intake, review, automatic
audit execution, proposal review, and a cited Markdown/JSON download. The
69-image baseline remains closed unless a functional failure indicates a shared
regression.

## Source map

```text
src/
├── app/             # synthetic fallback state and narrow native core boundaries
├── components/      # shell and shared UI primitives
├── pages/           # canonical route surfaces
├── styles/          # tokens, shell, components, and page systems
└── test/            # Vitest route, privacy, and accessibility tests
e2e/                 # Playwright smoke and screenshot contracts
public/              # packaged local assets
src-tauri/           # typed supervisor, Keychain/key-lease seam, and route commands
```

The webview owns presentation only. Production parsing, persistence, provider
access, evidence, and security policy belong to `services/core` behind the
typed Rust boundary; they must not be added directly to page components.

## Current desktop boundary

- Current Rust source exposes only the generated route-specific 57-operation/55-path
  allowlist and independently validates native responses; there is no generic core proxy.
  The latest completed packaged lifecycle is the current 57-operation build; every earlier build retains its own historical identity.
- The debug supervisor owns the one-shot bootstrap token, child process,
  bounded readiness, authenticated requests, and shutdown.
- A macOS Keychain custodian is wired to the anonymous FD-198 key lease; the
  automated full lifecycle uses a synthetic in-memory custodian.
- Native Rust enforces the current 300-second idle default and observes macOS
  sleep/wake, screen, and session transitions. System lock synchronously revokes
  the lease and restarts locked; physical sleep and real-Keychain prompting are
  still manual validation gates.
- React uses narrow commands for current native vault/profile/intake/review/
  graph/AI/query/public-search/HIBP/investigation-plan/findings/checkpoint/
  comparison/remediation/report slices. OpenAI and HIBP credentials are supplied
  only for one request and are not saved as settings. Browser fallback and broader
  audit surfaces remain synthetic.
- Discovery Console manual portals are fixed user-opened links. No UI path
  bypasses authentication, CAPTCHA, paywalls, plan gates, verification, or rate limits.
- The advanced query composer shows the exact query built from `site`, `filetype`,
  `intitle`, `inurl`, exclusion, date, and optional raw provider-specific operators.
  Google, Bing, DuckDuckGo, Brave, Ecosia, Startpage, and Mojeek are browser
  handoffs only; the composer performs no scraping or automatic evidence import.
- Display preferences support 90%, 100%, 110%, 125%, and 140% font scale plus
  Auto, Laptop, Standard, and Ultrawide presets. They are local presentation
  state and contain no workspace data.
- The local Tauri packaging spike passed private `0600` UDS startup, a `0700`
  runtime directory, authenticated capabilities and workflow requests, zero TCP
  listeners, sidecar environment non-inheritance, and requested/abrupt cleanup.
  Requested quit and SIGKILL startup completed in 6,974/5,511 ms with exit
  0/-9; each run used two sidecar processes and removed the processes, socket,
  and runtime directory. Deep bundle and strict main/sidecar ad-hoc signature
  checks passed.
- Release work still requires physical power/Keychain validation, one-identity
  hardened-runtime nested signing, notarisation, and a clean macOS 14 test.

The reproducible CommonCrypto and frozen-sidecar commands are documented in
[the packaging workflow](../../scripts/package-sidecar/README.md).

To reproduce the completed Tauri packaging spike after freezing the sidecar:

```sh
make stage-frozen-sidecar FROZEN_OUTPUT_ROOT=...
make package-spike-app
make package-spike-app-check
```

The staged target-suffixed binary under `src-tauri/binaries` is ignored and must
not be committed. `tauri.packaging-spike.conf.json` explicitly overlays the
external-binary setting for this local build.

That overlay also disables hardened runtime intentionally for the ad-hoc proof.
Tauri's ad-hoc re-sign of the PyInstaller sidecar otherwise caused the
one-file-extracted `libpython` to fail Team-ID library validation. This is not a
release trade-off: production must retain hardened runtime and use the same
Developer ID through the freezer, sidecar, Tauri, and final bundle before
notarisation and clean-machine validation.

## Safety rules

- Never import from or package confidential reference directories.
- Never add real credentials, live domains, provider responses, exact private coordinates, or identity material.
- Keep simulated runs visibly labelled as simulations with no external requests.
- Do not turn blocked access into bypass logic; provide lawful manual capture or import paths.
- Do not add automatic send, submit, removal, accusation, or provider-contact actions.
- Run the privacy check before staging or sharing work.

See [SECURITY.md](../../SECURITY.md), [PRIVACY_MODEL.md](../../PRIVACY_MODEL.md), and [KNOWN_LIMITATIONS.md](../../KNOWN_LIMITATIONS.md) before extending the prototype.
