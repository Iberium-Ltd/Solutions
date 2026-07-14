#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=versions.env
source "$SCRIPT_DIR/versions.env"

fail() {
  printf 'frozen inspection failed: %s\n' "$*" >&2
  exit 1
}

[[ $# -ge 2 && $# -le 3 ]] || {
  printf 'usage: %s FROZEN_BINARY PYI_ARCHIVE_VIEWER [RESULT_JSON]\n' "$0" >&2
  exit 2
}

BINARY="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
ARCHIVE_VIEWER="$2"
RESULT_JSON="${3:-}"
[[ -x "$BINARY" ]] || fail "frozen binary is unavailable"
[[ -x "$ARCHIVE_VIEWER" ]] || fail "PyInstaller archive viewer is unavailable"

for command_name in codesign file lipo otool shasum vtool; do
  command -v "$command_name" >/dev/null 2>&1 || fail "missing command: $command_name"
done

file_output="$(file "$BINARY")"
printf '%s\n' "$file_output"
grep -Fq 'Mach-O 64-bit executable arm64' <<<"$file_output" || fail "binary is not native arm64"
[[ "$(lipo -archs "$BINARY")" == "arm64" ]] || fail "binary has unexpected architectures"

build_version="$(vtool -show-build "$BINARY")"
printf '%s\n' "$build_version"
minimum_os="$(awk '$1 == "minos" { print $2; exit }' <<<"$build_version")"
minimum_major="${minimum_os%%.*}"
(( minimum_major <= 14 )) || fail "binary requires macOS $minimum_os"

dependencies="$(otool -L "$BINARY")"
printf '%s\n' "$dependencies"
if grep -Eiq '/opt/homebrew|/usr/local|libcrypto|libssl|libsqlcipher|libsqlite' <<<"$dependencies"; then
  fail "binary has a forbidden external database or crypto dependency"
fi

codesign --verify --strict "$BINARY"
archive_listing="$($ARCHIVE_VIEWER --list "$BINARY")"
grep -Fq 'pysqlcipher3/_sqlite3.cpython-312-darwin.so' <<<"$archive_listing" || fail "static SQLCipher extension is absent"
grep -Fq 'libpython3.12.dylib' <<<"$archive_listing" || fail "Python runtime is absent"
grep -Fq 'ariadne_core_migrations/alembic.ini' <<<"$archive_listing" || fail "Alembic configuration is absent"
grep -Fq 'ariadne_core_migrations/migrations/versions/0001_phase2_foundation.py' <<<"$archive_listing" || fail "foundation migration is absent"
grep -Fq 'ariadne_core_migrations/migrations/versions/0002_job_dependencies.py' <<<"$archive_listing" || fail "dependency migration is absent"
grep -Fq 'ariadne_core_migrations/migrations/versions/0003_intake_identity_graph.py' <<<"$archive_listing" || fail "intake identity migration is absent"
grep -Fq 'ariadne_core_migrations/migrations/versions/0004_entity_decision_policy_hardening.py' <<<"$archive_listing" || fail "decision policy migration is absent"
grep -Fq 'ariadne_core_migrations/migrations/versions/0005_graph_edge_origins.py' <<<"$archive_listing" || fail "graph edge origin migration is absent"
grep -Fq 'ariadne_core_migrations/migrations/versions/0006_query_policy_core.py' <<<"$archive_listing" || fail "query policy migration is absent"
grep -Fq 'ariadne_core_migrations/migrations/versions/0007_phase5_evidence_attribution.py' <<<"$archive_listing" || fail "Phase 5 evidence and attribution migration is absent"
grep -Fq 'ariadne_core_migrations/migrations/versions/0008_phase6_audit_remediation.py' <<<"$archive_listing" || fail "Phase 6 audit and remediation migration is absent"

binary_bytes="$(stat -f '%z' "$BINARY")"
(( binary_bytes > 1000000 && binary_bytes < 67108864 )) || fail "binary size is outside the approved bound"
binary_sha256="$(shasum -a 256 "$BINARY" | awk '{print $1}')"

if [[ -n "$RESULT_JSON" ]]; then
  uv run --project "$SCRIPT_DIR/../../services/core" --frozen \
    python "$SCRIPT_DIR/verify_frozen_sidecar.py" "$BINARY" | tee "$RESULT_JSON"
else
  uv run --project "$SCRIPT_DIR/../../services/core" --frozen \
    python "$SCRIPT_DIR/verify_frozen_sidecar.py" "$BINARY"
fi

printf 'frozen inspection passed\n'
printf 'binary=%s\n' "$BINARY"
printf 'sha256=%s\n' "$binary_sha256"
printf 'bytes=%s\n' "$binary_bytes"
printf 'architecture=arm64\n'
printf 'minos=%s\n' "$minimum_os"
