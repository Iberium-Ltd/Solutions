#!/usr/bin/env bash
# Stage only an already-inspected freezer artifact into Tauri's ignored binary
# directory, then compare digests. Staging is a copy boundary, never a rebuild or
# a reason to trust an older binary with the same filename.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

fail() {
  printf 'sidecar staging failed: %s\n' "$*" >&2
  exit 1
}

[[ $# -eq 1 ]] || {
  printf 'usage: %s FROZEN_OUTPUT_ROOT\n' "$0" >&2
  exit 2
}

OUTPUT_ROOT="$(cd "$1" && pwd)"
BINARY="$OUTPUT_ROOT/dist/ariadne-core-aarch64-apple-darwin"
ARCHIVE_VIEWER="$OUTPUT_ROOT/freezer-venv/bin/pyi-archive_viewer"
DESTINATION_DIR="$ROOT/apps/desktop/src-tauri/binaries"
DESTINATION="$DESTINATION_DIR/ariadne-core-aarch64-apple-darwin"

[[ -x "$BINARY" ]] || fail "frozen binary is unavailable"
[[ -x "$ARCHIVE_VIEWER" ]] || fail "matching PyInstaller archive viewer is unavailable"
[[ ! -L "$DESTINATION_DIR" ]] || fail "destination directory must not be a symlink"

"$SCRIPT_DIR/inspect_frozen_sidecar.sh" "$BINARY" "$ARCHIVE_VIEWER"

mkdir -p "$DESTINATION_DIR"
[[ ! -L "$DESTINATION" ]] || fail "destination must not be a symlink"
install -m 0755 "$BINARY" "$DESTINATION"

source_sha256="$(shasum -a 256 "$BINARY" | awk '{print $1}')"
staged_sha256="$(shasum -a 256 "$DESTINATION" | awk '{print $1}')"
[[ "$source_sha256" == "$staged_sha256" ]] || fail "staged binary digest mismatch"

printf 'Tauri sidecar staging passed\n'
printf 'DESTINATION=%s\n' "$DESTINATION"
printf 'SHA256=%s\n' "$staged_sha256"
