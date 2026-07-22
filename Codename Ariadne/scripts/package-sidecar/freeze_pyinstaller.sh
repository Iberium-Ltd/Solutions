#!/usr/bin/env bash
# Produce a self-contained arm64 sidecar from the inspected SQLCipher package.
# This creates release evidence in a fresh output tree; it never treats the
# development uv environment or a previously staged binary as a build input.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# shellcheck source=versions.env
source "$SCRIPT_DIR/versions.env"

fail() {
  printf 'freezer build failed: %s\n' "$*" >&2
  exit 1
}

[[ $# -le 1 ]] || { printf 'usage: %s [EMPTY_OUTPUT_DIRECTORY]\n' "$0" >&2; exit 2; }
if [[ $# -eq 1 ]]; then
  OUTPUT_ROOT="$1"
  mkdir -p "$OUTPUT_ROOT"
  [[ -z "$(find "$OUTPUT_ROOT" -mindepth 1 -maxdepth 1 -print -quit)" ]] || fail "output directory must be empty"
else
  OUTPUT_ROOT="$(mktemp -d /tmp/ariadne-frozen-sidecar.XXXXXX)"
fi
OUTPUT_ROOT="$(cd "$OUTPUT_ROOT" && pwd)"

DRIVER_ROOT="$OUTPUT_ROOT/sqlcipher"
FREEZER_ENV="$OUTPUT_ROOT/freezer-venv"
BUILD_ROOT="$OUTPUT_ROOT/pyinstaller-build"
DIST_ROOT="$OUTPUT_ROOT/dist"
LOG_ROOT="$OUTPUT_ROOT/logs"
LICENSE_ROOT="$OUTPUT_ROOT/licenses"
mkdir -p "$BUILD_ROOT" "$DIST_ROOT" "$LOG_ROOT" "$LICENSE_ROOT"

"$SCRIPT_DIR/build_sqlcipher_commoncrypto.sh" "$DRIVER_ROOT" \
  > "$LOG_ROOT/sqlcipher-build.log" 2>&1
DRIVER_PACKAGE="$DRIVER_ROOT/package"
# Replace any resolver-supplied binding with the just-built inspected artifact.
# This prevents an ABI-compatible plaintext SQLite module from entering the
# frozen archive unnoticed.
[[ -f "$DRIVER_PACKAGE/pysqlcipher3/dbapi2.py" ]] || fail "static SQLCipher package is unavailable"

uv export --directory "$ROOT" --frozen --package ariadne-core --no-dev \
  --no-emit-project --prune pysqlcipher3 --no-hashes --no-header --no-annotate \
  --output-file "$OUTPUT_ROOT/runtime-requirements.txt"
uv venv --python "$CPYTHON_VERSION" "$FREEZER_ENV"
uv pip install --python "$FREEZER_ENV/bin/python" \
  --requirements "$OUTPUT_ROOT/runtime-requirements.txt" \
  "pyinstaller==$PYINSTALLER_VERSION" \
  "pyinstaller-hooks-contrib==$PYINSTALLER_HOOKS_CONTRIB_VERSION" \
  "altgraph==$ALTGRAPH_VERSION" \
  "macholib==$MACHOLIB_VERSION" \
  "setuptools==$SETUPTOOLS_VERSION"
uv pip install --python "$FREEZER_ENV/bin/python" --no-deps "$ROOT/services/core"

SITE_PACKAGES="$($FREEZER_ENV/bin/python -c 'import site; print(site.getsitepackages()[0])')"
rm -rf "$SITE_PACKAGES/pysqlcipher3"
cp -R "$DRIVER_PACKAGE/pysqlcipher3" "$SITE_PACKAGES/"
cp -R "$DRIVER_PACKAGE/licenses/." "$LICENSE_ROOT/"

export MACOSX_DEPLOYMENT_TARGET
export PYTHONPATH="$DRIVER_PACKAGE:$ROOT/services/core/src"
codesign_mode=adhoc
if [[ -n "${ARIADNE_CODESIGN_IDENTITY:-}" ]]; then
  set -- --codesign-identity "$ARIADNE_CODESIGN_IDENTITY"
  codesign_mode=developer_id
else
  set --
fi
"$FREEZER_ENV/bin/pyinstaller" \
  --clean --noconfirm --onefile --noupx \
  --name ariadne-core-aarch64-apple-darwin \
  --target-architecture arm64 \
  --distpath "$DIST_ROOT" \
  --workpath "$BUILD_ROOT/work" \
  --specpath "$BUILD_ROOT/spec" \
  --paths "$ROOT/services/core/src" \
  --paths "$DRIVER_PACKAGE" \
  --add-data "$ROOT/services/core/alembic.ini:ariadne_core_migrations" \
  --add-data "$ROOT/services/core/migrations:ariadne_core_migrations/migrations" \
  --hidden-import pysqlcipher3._sqlite3 \
  "$@" \
  "$ROOT/services/core/src/ariadne_core/cli.py" \
  > "$LOG_ROOT/pyinstaller.log" 2>&1

BINARY="$DIST_ROOT/ariadne-core-aarch64-apple-darwin"
[[ -x "$BINARY" ]] || fail "PyInstaller produced no sidecar"
"$SCRIPT_DIR/inspect_frozen_sidecar.sh" \
  "$BINARY" "$FREEZER_ENV/bin/pyi-archive_viewer" "$OUTPUT_ROOT/lifecycle-results.json" \
  | tee "$LOG_ROOT/frozen-inspection.log"

binary_sha256="$(shasum -a 256 "$BINARY" | awk '{print $1}')"
binary_bytes="$(stat -f '%z' "$BINARY")"
{
  printf 'freezer=PyInstaller\n'
  printf 'freezer_version=%s\n' "$PYINSTALLER_VERSION"
  printf 'freezer_hooks_version=%s\n' "$PYINSTALLER_HOOKS_CONTRIB_VERSION"
  printf 'codesign_mode=%s\n' "$codesign_mode"
  printf 'python_version=%s\n' "$CPYTHON_VERSION"
  printf 'target=arm64-apple-darwin\n'
  printf 'macos_deployment_target=%s\n' "$MACOSX_DEPLOYMENT_TARGET"
  printf 'sqlcipher_version=%s\n' "$SQLCIPHER_VERSION"
  printf 'sqlite_version=%s\n' "$SQLCIPHER_SQLITE_VERSION"
  printf 'binary_sha256=%s\n' "$binary_sha256"
  printf 'binary_bytes=%s\n' "$binary_bytes"
} > "$OUTPUT_ROOT/FREEZER-MANIFEST.txt"

printf 'frozen sidecar build passed\n'
printf 'OUTPUT_ROOT=%s\n' "$OUTPUT_ROOT"
printf 'BINARY=%s\n' "$BINARY"
