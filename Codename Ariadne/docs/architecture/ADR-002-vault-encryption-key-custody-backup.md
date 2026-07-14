# ADR-002: Vault Encryption, Key Custody, and Backup

- Status: Accepted for the Phase 2 local foundation
- Date: 2026-07-11
- Decision owners: Security, privacy, desktop, and core-service engineering
- Scope: macOS arm64 vault creation, lock/unlock, migration safety, and small-vault backup/restore

## Context

The local foundation must protect settings, task state, audit history, and later identity data when the application is closed or the vault is locked. It must also distinguish an encrypted vault opened with the wrong key from a new empty database. A stolen database, WAL file, backup, or copied vault directory must not expose plaintext.

The target application declares macOS 14 as its minimum version. The current Homebrew SQLCipher 4.17.0 and OpenSSL 4 bottles are useful development references on the target Mac, but their Mach-O load commands require macOS 26 and their dynamic-library paths point into `/opt/homebrew`. They are therefore not release inputs.

Phase 2 needs a verifiable backup and recovery path before evidence volumes become large. A later format may need streaming, portability between Macs, and independently encrypted evidence objects; those requirements must not be guessed into the first format.

The master prompt defines Phase 2 as the local foundation and Phase 9 as release hardening. Version metadata and purpose-separated keys are established here, but production database-key/backup-key rotation, physical sleep and platform-Keychain prompt exercises, Developer ID signing, notarisation, and clean-machine validation are Phase 9 gates. They are deliberately not represented as completed Phase 2 behavior.

## Decision

### SQLCipher baseline

Use SQLCipher Community 4.17 or newer with its embedded SQLite at version 3.51.3 or newer. The packaged arm64 library is built from pinned source with the CommonCrypto backend and `MACOSX_DEPLOYMENT_TARGET=14.0`.

The runtime must verify all of the following through the same DBAPI connection that will run migrations:

- `PRAGMA cipher_version` reports the approved SQLCipher family;
- `sqlite_version()` is at least 3.51.3 and matches the packaged build manifest;
- codec support, foreign keys, JSON, FTS5, busy timeout, temp policy, and the selected journal policy are active;
- a keyed database passes SQLCipher and SQLite integrity checks before normal use.

There is no plaintext SQLite fallback. Failure to load the SQLCipher driver, obtain a key, authenticate the database, validate its header, or verify its version is a locked or recovery-required error. It must never cause creation of a replacement database at the same path. Plaintext migration, if ever supported, requires a separate explicit import decision and is not part of Phase 2.

Homebrew SQLCipher may be used only for an explicitly labelled development spike. Release and compatibility tests reject Homebrew load paths, a deployment target above macOS 14, a non-arm64 binary, or an unbundled native dependency.

### Key hierarchy and custody

Each vault has two independent random 256-bit keys:

1. A database key for SQLCipher.
2. A backup-envelope key for Phase 2 backup authentication and encryption.

Both keys are created with the operating-system cryptographic random source and are held as separate macOS Keychain items. The database stores only opaque, non-secret Keychain references and key-version metadata. Keys are never derived from identity material, vault names, device identifiers, environment variables, command-line arguments, frontend state, or application logs.

Core code depends on an injectable `KeyCustody` interface with operations to create, authorize, load, rotate, and delete a versioned vault key. The production adapter is mediated by the Rust shell and macOS Keychain. Unit and CI tests use an isolated in-memory or temporary-keychain adapter containing synthetic random keys. No test touches the user's normal Keychain items.

Key bytes never enter the webview or a logical API request/response. The privileged boundary releases them only to the vault-opening or backup operation after authorization. The core retains them only while the vault is unlocked, avoids copies where practical, and overwrites mutable buffers on lock as a best-effort memory-hygiene measure. This does not claim protection from a process already running with the user's privileges.

Database-key rotation and backup-key rotation will remain independently versioned. The foundation persists closed key-version metadata and rejects unsupported versions; it exposes no incomplete rotation command. Phase 9 must implement rotation by writing and verifying new encrypted state before changing the active Keychain reference. The prior key must remain available until verification succeeds, then be removed according to the recovery policy.

### Phase 2 backup envelope

Phase 2 uses a versioned AES-256-GCM authenticated envelope around a consistent SQLCipher database snapshot and a strict canonical metadata header. The backup key is distinct from the SQLCipher key. Each backup uses a fresh 96-bit nonce from the operating-system random source; nonce reuse for a key is a hard failure. The format identifier, format version, vault identifier, key version, creation time, declared plaintext length, source digest, and nonce are authenticated as associated data.

The decrypted payload contains only the consistent SQLCipher snapshot. The bounded canonical header is authenticated but not encrypted and contains only the minimum non-secret metadata required to validate and restore that snapshot. Unknown, missing, non-canonical, ill-typed, or out-of-range header fields fail closed before decryption.

The Phase 2 envelope is deliberately bounded to 64 MiB of plaintext and 64 MiB plus fixed envelope overhead on disk. Encryption and decryption may therefore be one-shot operations. Inputs exceeding the bound fail before allocation or overwrite. Evidence-object backup, large-vault streaming, removable-media portability, user-held recovery secrets, and cross-device key transfer require a later streaming/portability ADR before the limit can be raised.

The Phase 2 backup is recoverable only while its matching backup key remains available through authorized Keychain custody. The UI must state this limitation and must not describe it as an archival or cross-device recovery guarantee.

### Backup creation

Backup creation:

1. Requires an unlocked, integrity-checked vault and an authorized backup key.
2. Generates and durably reserves the nonce for the active backup-key version; the unique reservation remains even after failure so the nonce cannot be reused.
3. Produces a consistent SQLCipher snapshot using the approved database backup mechanism, not an ordinary copy of a live database file.
4. Builds and bounds the strict canonical metadata header before encryption.
5. Writes the envelope to a new private temporary file on the destination volume.
6. Flushes and verifies the complete envelope, including an authenticated decrypt-and-manifest check.
7. Atomically renames the verified file to the user-selected destination where the filesystem supports it.
8. Records only destination class, format/key versions, nonce, size, ciphertext digest, and verification state; routine logs never record the absolute path.

A failed or cancelled operation leaves no successful backup record. A clearly suffixed partial file may remain only long enough for startup cleanup and is never offered as a valid backup.

### Locked restore and atomic replacement

Restore is allowed only while the destination vault is locked. It never mutates the active vault in place.

The shell obtains backup-key authorization out of band. The core then performs bounded header parsing, AES-GCM authentication, manifest validation, SQLCipher authentication, version compatibility checks, migrations when required, foreign-key and integrity checks, and a representative read in a private staging directory on the same volume as the destination vault.

Only a fully verified staged vault may replace the active vault. The implementation flushes staged files and required directory metadata, renames the current vault to a recovery name, atomically renames the staged vault into place, opens and verifies the replacement, and retains the prior encrypted vault until that post-swap verification succeeds. Any failure restores or preserves the prior vault and records a redacted recovery state.

Cross-volume replacement, following symlinks, restoring through an untrusted pre-existing staging path, restoring over an unlocked vault, and accepting an unknown future format all fail closed. The application does not claim atomic directory replacement or permission preservation on filesystems where tests cannot prove those properties.

### File and lock behavior

Vault directories are private to the user, database and backup staging files are mode `0600`, and directories are mode `0700`. Temporary plaintext database copies are prohibited. SQLCipher WAL and SHM files remain beside the encrypted database and receive the same ownership boundary. Startup refuses unsafe ownership, symlinks, unsupported file types, or unexpectedly permissive modes rather than silently repairing a potentially substituted vault.

Deleting Keychain keys provides application-level cryptographic erasure for remaining ciphertext, but the product does not promise physical overwrite on APFS, SSD wear-levelled media, snapshots, exported copies, or third-party backups.

## Alternatives considered

### Homebrew SQLCipher and OpenSSL in the application bundle

Rejected for packaging. The observed bottles target macOS 26 and retain Homebrew dynamic paths, conflicting with the declared macOS 14 minimum and clean-machine execution. They remain useful only as a local behavior spike.

### Plain SQLite with selected encrypted columns

Rejected. It would expose schema, indexes, jobs, settings, WAL contents, and correlation metadata and would make omission errors likely.

### Password-derived vault keys

Deferred. Password UX, recovery, KDF parameters, brute-force resistance, and cross-device portability require a separate product decision. Phase 2 uses random Keychain-custodied keys.

### Reusing the database key for backups

Rejected. Separate keys provide purpose separation, independent rotation, and the ability to revoke backup recovery without rewriting the active database.

### Streaming encryption immediately

Deferred. AES-GCM is not a streaming file format by itself. Chunk framing, nonce derivation, truncation resistance, random access, evidence objects, and portable recovery need a separate versioned design. The hard Phase 2 size bound keeps the one-shot envelope honest.

## Verification requirements

The Phase 2 local-foundation gate uses automated tests to prove:

- no-key, wrong-key, missing-driver, plaintext-file, old-version, and future-version opens fail without creating or changing a vault;
- the actual DBAPI reports the approved SQLCipher/SQLite build and required features;
- database, WAL, SHM, temporary, and backup files contain none of several generated plaintext canaries;
- bit flips, truncation, wrong keys, wrong associated data, nonce-policy violations, missing/extra/non-canonical metadata, declared-length mismatches, and digest mismatches fail closed;
- interrupted backup, migration, and every restore phase leaves the prior encrypted vault recoverable;
- restore is same-volume, locked, staged, verified, and atomic at the selected replacement boundary;
- unsupported key versions cannot activate and lock removes all active capabilities;
- packaged native libraries are arm64, target macOS 14, use bundle-relative load paths, and pass nested signature checks; and
- backup size and allocation limits are enforced before expensive work.

Before release with real data, Phase 9 additionally requires crash-safe database-key and backup-key rotation, the real platform-Keychain and physical sleep/wake exercises, one Developer ID across nested code, hardened runtime, notarisation/stapling, and clean macOS 14 validation.

## Consequences

The decision gives Phase 2 an encrypted-by-construction database and a narrow, testable local recovery path. It also makes Keychain loss an explicit recovery limitation and caps initial backup size. Packaging must own a pinned CommonCrypto SQLCipher build rather than copying the target machine's Homebrew libraries.

Before evidence-heavy or cross-device backup is enabled, a later ADR must define chunked authenticated encryption, evidence-object inclusion, key portability/recovery, cancellation checkpoints, and compatibility rules.
