# Reproducible macOS arm64 sidecar packaging

Status: The 57-operation/55-path aggregate, frozen sidecar, and packaged-app lifecycle pass at `0011_profile_purge`. The verified 48-operation `0008` artifact remains historical and separately identified; production signing remains Phase 9 work.

This spike builds the Python DB-API extension used by the local core without
linking to Homebrew SQLCipher, OpenSSL, or the system SQLite library. It fetches
hash-pinned official SQLCipher Community 4.17.0 and PyPI pysqlcipher3 1.2.0
source archives, generates the SQLCipher 4.17.0 / SQLite 3.53.3 amalgamation,
and compiles it directly into a CPython 3.12 arm64 extension with CommonCrypto.

No third-party source or binary is written into the repository. The default
output is a fresh directory under `/tmp`; an explicit output directory must be
empty. Keep generated output ignored and outside Git. These intermediate build
artifacts are not committed Tauri resources or release binaries; only the
inspected frozen executable is staged into the ignored Tauri binary directory.

## Development versus packaged inputs

`scripts/bootstrap_core.sh` creates the uv development environment and links
`pysqlcipher3` to the target Mac's Homebrew SQLCipher for quick tests. That
machine-local extension must never enter a release bundle.

This directory is the separate reproducible path. It builds SQLCipher from
hash-pinned source with CommonCrypto and then substitutes that inspected package
into a clean freezer environment. A frozen artifact is accepted only after the
Homebrew/OpenSSL linkage checks and live TCP/UDS lifecycle checks pass.

## Pinned inputs

`versions.env` records:

- SQLCipher tag `v4.17.0`, resolved commit, official GitHub archive URL, and
  SHA-256;
- pysqlcipher3 1.2.0 official PyPI source URL and SHA-256;
- CPython 3.12.13; and
- deployment target macOS 14.0.

The small source patch replaces removed CPython-private Unicode helpers with
the public Python 3.12 API. It does not change SQLCipher behavior. SQLCipher is
built from its verified archive and uses `SQLCIPHER_CRYPTO_CC`; no Homebrew
header or library path is supplied.

## Prerequisites

- Native Apple Silicon macOS.
- Xcode Command Line Tools with the macOS SDK, `clang`, `otool`, and `vtool`.
- `curl`, `make`, `patch`, `shasum`, and `tar`.
- `uv` with CPython 3.12.13, or an explicit arm64 CPython 3.12 executable in
  `PYTHON_BIN`.

## Run

Create a fresh temporary build:

```sh
scripts/package-sidecar/build_sqlcipher_commoncrypto.sh
```

Or preserve it at a known ignored path:

```sh
scripts/package-sidecar/build_sqlcipher_commoncrypto.sh \
  /tmp/ariadne-sqlcipher-package-final
```

The command prints `OUTPUT_ROOT`, `PACKAGE_DIR`, and `EXTENSION`. It preserves
download, configure, amalgamation, compiler, and inspection logs if a phase
fails. `ARIADNE_BUILD_JOBS` may be set from 1 through 16 and defaults to 4.

Re-run inspection independently with:

```sh
scripts/package-sidecar/inspect_sqlcipher_commoncrypto.sh \
  /tmp/ariadne-sqlcipher-package-final/package
```

## Inspection contract

Inspection fails unless:

- the extension is a native arm64 Mach-O bundle;
- `vtool` reports minimum macOS 14.0;
- `otool` contains no `/opt/homebrew`, `/usr/local`, `libcrypto`, `libssl`,
  `libsqlcipher`, or dynamic `libsqlite` dependency;
- unresolved symbols prove the CommonCrypto cipher, HMAC, and PBKDF provider;
- runtime `PRAGMA cipher_version` reports SQLCipher 4.17.0 Community;
- runtime SQLite is at least 3.51.3 and the generated build reports 3.53.3;
- codec, FTS5, JSON, thread-safety, and in-memory temp support work; and
- an encrypted round trip succeeds while missing-key and wrong-key reads fail,
  the file has no plaintext SQLite header, and a plaintext canary is absent.

This produces an importable package directory rather than a release wheel. The
frozen-sidecar integration copies it into a clean freezer input.

## Frozen sidecar

The Phase 2 spike selects pinned PyInstaller 6.21.0 in one-file mode. Its
hooks, `altgraph`, `macholib`, and `setuptools` freezer inputs are also exact
version pins. Build the driver and frozen sidecar together with:

```sh
scripts/package-sidecar/freeze_pyinstaller.sh \
  /tmp/ariadne-frozen-sidecar-final
```

The equivalent root target uses a fresh temporary output directory:

```sh
make frozen-sidecar-spike
```

The script exports runtime dependencies from the checked `uv.lock`, removes the
registry SQLCipher binding, substitutes the inspected CommonCrypto package,
freezes `ariadne_core.cli`, and exercises both authenticated TCP-development and
private-UDS modes. UDS verification installs the anonymous key channel at FD
198 and validates the nonce-bound HELLO through the PyInstaller outer/inner
topology. It also verifies replay, wrong-token, wrong-Origin, cleanup,
architecture, deployment target, archive contents, signature, size, and the
absence of external SQLCipher/OpenSSL load paths.

The historical final Phase 3 arm64 executable is 20,403,456 bytes with SHA-256
`c4a77933840a32d8751235eeeeea70a5d55f670869c7db8cd5499f04184cdf93`
and minimum macOS 11.0. Its UDS probe creates an encrypted vault at
`0005_graph_edge_origins`, creates a synthetic profile, performs paste intake
containing a restricted value, verifies quarantine and entity review, and
confirms restricted plaintext is absent from routine responses.

Ad-hoc signing intentionally changes the Mach-O bytes. The packaged signed
sidecar is 20,403,440 bytes with SHA-256
`bb021e1033b63b1407cd71007a6d4cfb375990ed991e13c54fa7a91fb2861e10`;
the desktop executable is 13,277,088 bytes with SHA-256
`6398472fc3af6d72f3539c947c37b2e96ed617f85fc13d0712cfcb37005fef2f`.
`codesign --verify --deep --strict` passes. Packaged normal quit reports 3,013
ms startup and cleanup true; abrupt SIGKILL reports 2,374 ms startup and cleanup
true. Both runs have zero TCP listeners, a `0700` runtime directory, and `0600`
socket. These are conservative launch-to-complete-workflow measurements, not
release startup guarantees.

The preserved Phase 4 candidate includes migration `0006_query_policy_core`,
native Graph, four local-AI operations, three network-free query-policy
operations, and selected-model intake enrichment. Its aggregate and final
313-candidate privacy scan passed. Its staged arm64 sidecar is 20,481,200 bytes
with SHA-256
`bd522b5b10a92cca552f4b062723bf3d016c01ab0dcb2fad2c9d9112eaebce67`,
minimum macOS 11.0, and schema head `0006_query_policy_core`; its authenticated
UDS startup completed in 7,866 ms and the workflow passed.

The package was rebuilt after the Settings review-requirement copy changed to
present tense. Requested quit starts in 2,767 ms and abrupt SIGKILL in 2,532 ms;
both clean up, expose zero TCP, and preserve a `0700` runtime directory and
`0600` socket. The signed packaged sidecar is 20,481,184 bytes with SHA-256
`eb4eae99e52d2c08efa918f61fa20fcee4a2fcffa9dba87892075138923a73bd`;
the desktop executable is 13,803,520 bytes with SHA-256
`9e14c54b34ab5eaf307838e25488957b34ecb5f86cb526bff8914a8d0c4b26b3`.
Deep strict code-signature verification passes. These identities, not the
historical Phase 3 hashes above, are the preserved `0006` evidence.

The separately verified Phase 5 read milestone advances the source and frozen
archive to `0007_phase5_evidence_attribution`. Its aggregate includes a clean
327-candidate privacy scan. The staged arm64 sidecar is 20,550,480 bytes with
SHA-256
`5d4856853db1e8194d2a3930830081bcdba50c31457acca151b0ea972c5059a4`;
the ad-hoc signed packaged sidecar is 20,550,464 bytes with SHA-256
`fe0e7d5bc7aebe1aa83b21745612b68d82c444a0f7af10b43ac58ecdb2d4a47c`;
and the 14,124,624-byte desktop executable has SHA-256
`2cd7cc41ff1c4bc6ce71e9dab1b9efe91c21ab8ffdabb59ca330bf6dd0604e0b`.
Requested quit and abrupt SIGKILL started in 2,556 ms and 1,921 ms,
respectively; both cleaned up, opened zero TCP listeners, preserved `0700` and
`0600` runtime modes, and passed deep strict code-signature verification.

Nuitka remains deferred. PyInstaller already met the Phase 2 functional,
architecture, deployment-target, dependency, size, and startup gates with a
much smaller integration surface. Reconsider Nuitka only if later clean-machine
startup, signing/notarisation, performance, or optional native-model packaging
tests expose a concrete PyInstaller limitation.

The verified `0007` service surface contained 22 generated operations. The
earlier `0008_phase6_audit_remediation` package contains 37 generated
operations (4 GET, 33 POST): the prior 22, three bounded Phase 5 write
operations, and twelve Phase 6 audit/remediation operations. It exposes no
generic proxy, general jobs, backup, evidence-byte response/viewer,
network-provider, automatic provider snapshot-ingestion, or external-dispatch
route. The next historical source/package milestone at the same schema head
contains 40 operations (4 GET, 36 POST; 38 paths) by adding manual-finding
bootstrap, a user-triggered local checkpoint, and deterministic local report
generation. The next historical source/package milestone has 45 operations
(4 GET, 41 POST) across 43 paths and adds bounded public discovery/capture,
corpus AI, workspace AI, and complete entity-origin pagination without a
generic proxy or external-dispatch route. The next historical source candidate has
48 operations (4 GET, 44 POST) across 46 paths, adding official HIBP account/
domain checks and deterministic investigation-plan compilation. Its aggregate,
frozen-sidecar, and packaged-app lifecycle results pass under the historical
identities recorded below.

The historical 37-operation `0008` frozen output at
`/tmp/ariadne-phase6-package.GDaFwQ` is a
20,639,264-byte arm64/minimum-macOS-11 executable with SHA-256
`e156e9ec31e95ef76f2f84779796176a422f1cc90d6cee624cdbdb61b024f3de`.
Initial authenticated TCP/UDS verification completed in 3,353/4,470 ms and
staging re-verification in 1,925/4,355 ms with the same digest. The UDS probe
reported exact schema/archive `0008_phase6_audit_remediation` and all ten Phase
6 tables; dependency, archive, path/string, and 37-operation checks passed.

Its signed packaged sidecar is 20,639,248 bytes with SHA-256
`359fd0403dc23a99ea3aa19d18c2b3e83b2bc3ed205a3d7ef4f858fc3e6a032d`;
the 15,262,736-byte desktop executable has SHA-256
`fc02daef7835b4225cee27f769feee9302764f040037acf0e86a23e388235fc9`.
Requested quit and abrupt SIGKILL started in 2,325/1,927 ms, used two sidecar
processes, cleaned up, exposed zero TCP listeners, preserved `0700`/`0600`
runtime modes, and passed deep/main/sidecar strict ad-hoc signature checks.
The app uses 35,975,168 allocated bytes with 5 regular files/9 entries and the
expected identifier. The 341-candidate privacy scan passed. These identities
remain historical evidence and are not relabelled as later package proof.

The historical 40-operation frozen sidecar is a 20,694,992-byte arm64/minimum-
macOS-11 executable with SHA-256
`96c368b90692e452de2b14a58994105a7838ce5ad06231169f9d5d381234a610`.
It reports exact schema/archive `0008_phase6_audit_remediation`; authenticated
UDS requests for manual finding creation, baseline and current checkpoint
creation, and local report generation all returned 200. Architecture,
minimum-OS, dependency, archive, path/string denylist, and 40-operation checks
passed.

The historical 40-operation signed packaged sidecar is 20,694,976 bytes with SHA-256
`77338ee05e0f0b92e0483c0e9d936446b5a162285d9c75c09aa47ea4d0e69b94`;
the 15,510,800-byte arm64/minimum-macOS-14 desktop executable has SHA-256
`214ccd0f3fccfa9d42c2af7598d62f74693ec3cb01a7b585aac73a890e9fc053`.
Requested quit and abrupt SIGKILL started in 4,116/2,646 ms and exited 0/-9;
both used two sidecar processes, cleaned up, exposed zero TCP listeners, and
preserved `0700`/`0600` runtime modes. Deep bundle, main executable, and sidecar
strict ad-hoc signature checks passed. The matching source gate passes 372
Python tests in 383.52 seconds, 82 Rust tests plus one ignored manual-Keychain
test, 96 frontend tests across 23 files, 21/21 Chromium and 21/21 WebKit route/
accessibility smokes, exact 40-route parity, and a 354-candidate privacy scan.

The historical 45-operation/43-path artifact completed this verification workflow.
The staged arm64/minimum-macOS-11 sidecar is 20,892,240 bytes with SHA-256
`b33e411e95c4147ed3a16fe7894f490bcb47884c23703a1888f648638267831f`.
Ad-hoc packaging changed the Mach-O bytes: the packaged
arm64/minimum-macOS-11 sidecar is 20,892,224 bytes with SHA-256
`536c16a851d11676438899b5edc07de2bef11efa704648618149581602f8e82f`,
and the 16,435,024-byte arm64/minimum-macOS-14 desktop executable has SHA-256
`d3eef7bac068674849b9c3489caafe4887f76d6b53ed90d48b202276c711819f`.
Requested quit and abrupt SIGKILL started in 6,974/5,511 ms and exited 0/-9;
both used two sidecar processes, cleaned up the processes, socket, and runtime
directory, exposed zero TCP listeners, and preserved `0700`/`0600` runtime
modes. Deep bundle and strict main/sidecar ad-hoc signature verification
passed. These are conservative local workflow measurements and exact historical
45-operation artifact identities, not evidence for the later 48- or
57-operation sources, release startup guarantees, or release binaries.

The historical 48-operation frozen/staged arm64/minimum-macOS-11 sidecar is
20,946,896 bytes with SHA-256
`5ca6b790878cc7f77b99cc21e75e49c2febf8208dccbf87cb523669515262df3`.
Initial frozen TCP/UDS verification completed in 3,686/45,743 ms and staging
reinspection in 3,734/66,387 ms; both workflows passed. Ad-hoc packaging changed
the Mach-O bytes: the packaged 20,946,880-byte sidecar has SHA-256
`4ba7fd0a6f99135b96f412a4371c5f7783ffb6c4ae5cbe6ac1f8fd82d36d324b`
and CDHash `bac9d49b49c770a460ddae9698a4e39a12a4b92c`. The 16,979,744-byte
arm64/minimum-macOS-14 desktop has SHA-256
`ca68fdd4957c7540716f4e7a9b0d54cea657e44cb2bdf68cc012d67cada3d3ec`
and CDHash `f096565871d279b40f5196c51ae40a3e94cf9f3c`. Requested quit and abrupt
parent exit started in 3,290/2,550 ms and exited 0/-9; both used two sidecars,
cleaned up, exposed zero TCP listeners, and preserved `0700`/`0600` modes.
Deep strict ad-hoc bundle verification passed, and the bundle allocated 37,108
KiB. This proves a local candidate package, not a production release.

The current 57-operation/55-path frozen and staged sidecar reaches exact schema
head `0011_profile_purge`. It is a 21,053,600-byte
arm64/minimum-macOS-11 executable with SHA-256
`dccaaa5d3c9a60b668ecd85cdd0d00a79c4b16aadd2c02995e43891478a9d7f5`.
Fresh frozen and staged inspections passed authenticated TCP/UDS workflows.
Ad-hoc packaging produced a 21,053,584-byte sidecar with SHA-256
`74325b31abba5afb4f916051898c80431018cd4a0b8ae90a9f44f0183281d7b0`
and CDHash `396892d4ec3a4784ceb924ddff682987ac65d852`. The
17,815,088-byte arm64/minimum-macOS-14 desktop has SHA-256
`08491aabfc4d61daa61cf7b5137162b9a64403987b63468fa7e5031b19a8f81f`
and CDHash `ac7b5fed454dfeaddc391c468aed1fad20232b4f`. Requested quit
and abrupt parent exit started in 4,942/3,196 ms and exited 0/-9; both used two
sidecars, cleaned up, exposed zero TCP listeners, and preserved `0700`/`0600`
modes. Deep strict ad-hoc bundle verification passed, and the bundle allocated
38,032 KiB. This is local candidate proof, not a production release.

Developer-ID signing, notarisation, stapling, and a clean macOS 14 launch remain
release gates. Local Tauri resource integration and release-mode launch over a
private `0600` UDS are proven below; packaged mode must continue to reject TCP
fallback. The key lease is implemented; production signing and platform
Keychain confirmation remain separate release gates.

## Local Tauri application packaging spike

The frozen sidecar is now integrated into a local Tauri packaging proof without
committing the binary. Given the output root printed by
`freeze_pyinstaller.sh`, run:

```sh
make stage-frozen-sidecar FROZEN_OUTPUT_ROOT=...
make package-spike-app
make package-spike-app-check
```

`stage_tauri_sidecar.sh` re-runs frozen inspection, requires the matching
PyInstaller archive viewer, copies the binary to the ignored target-suffixed
`apps/desktop/src-tauri/binaries` path, and compares source/staged SHA-256.
`package-spike-app` then applies `tauri.packaging-spike.conf.json`, which alone
declares the external binary, and produces the local `.app`.

`package-spike-app-check` verifies the bundle identity, macOS 14 minimum,
arm64 main/sidecar executables, safe permissions, ad-hoc local signatures, and
absence of Homebrew/OpenSSL/SQLCipher/SQLite dynamic dependencies. It launches
the packaged application twice and proves:

- Rust spawns the frozen sidecar with exact UDS arguments and completes the
  authenticated capabilities handshake;
- the app, PyInstaller bootloader, and Python child open zero TCP listeners;
- the runtime directory is user-owned mode `0700` and `core.sock` is `0600`;
- a synthetic parent environment probe and session/bootstrap markers are not
  inherited by the sidecar; and
- requested quit and abrupt parent termination both remove the two sidecar
  processes, socket, and runtime directory within the cleanup bound.

### Hardened-runtime limitation of the local proof

`tauri.packaging-spike.conf.json` deliberately sets `hardenedRuntime` to false.
With local ad-hoc signing, Tauri re-signs the outer PyInstaller executable; the
library-validation entitlement then rejects its one-file-extracted `libpython`
because the nested code has no matching Team ID. Disabling hardened runtime is
acceptable only to isolate and verify local process/UDS packaging behavior.

Production must keep hardened runtime enabled and apply the same Developer ID
to freezer contents, the frozen sidecar, Tauri executables, and the final app
before notarisation, stapling, and clean-machine testing. The local overlay must
never be promoted to production configuration.

When a release identity is available, set `ARIADNE_CODESIGN_IDENTITY` for
`freeze_pyinstaller.sh`; the script passes it to PyInstaller so collected
Mach-O libraries and the outer sidecar share the release identity. The
corresponding Tauri production configuration must use that same identity. The
manifest records only `developer_id` versus `adhoc`, never the certificate
name.

The anonymous key handoff, native idle/system-lock dispatch, delayed-Keychain
revocation, and native profile/intake/entity-review/graph connection are
implemented and pass synthetic cross-language tests. The Graph screen consumes
the persisted, bounded graph snapshot with provenance; browser simulation remains
an explicit fallback. Physical sleep/wake, the manual platform-Keychain round
trip, production signing/notarisation, and broader audit-domain workflows remain
pending; the package spike does not make the synthetic UI an operational vault
interface. Before a later artifact is described as current package evidence,
the full aggregate, frozen inspection, Tauri lifecycle, permissions, zero-TCP,
cleanup, and signature gates must rerun and record fresh identities.
