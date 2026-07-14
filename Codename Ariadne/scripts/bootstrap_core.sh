#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required" >&2
  exit 1
fi

if ! command -v brew >/dev/null 2>&1 || ! brew --prefix sqlcipher >/dev/null 2>&1; then
  echo "Homebrew SQLCipher is required for the development verification build" >&2
  exit 1
fi

sqlcipher_prefix="$(brew --prefix sqlcipher)"
export C_INCLUDE_PATH="$sqlcipher_prefix/include"
export LIBRARY_PATH="$sqlcipher_prefix/lib"
export LDFLAGS="-L$sqlcipher_prefix/lib"

uv sync --all-packages --all-groups

temporary_output=""
package_dir="${ARIADNE_SQLCIPHER_PACKAGE_DIR:-}"
if [[ -z "$package_dir" ]]; then
  temporary_output="$(mktemp -d /tmp/ariadne-core-sqlcipher.XXXXXX)"
  "$SCRIPT_DIR/package-sidecar/build_sqlcipher_commoncrypto.sh" "$temporary_output"
  package_dir="$temporary_output/package"
else
  package_dir="$(cd "$package_dir" && pwd)"
  "$SCRIPT_DIR/package-sidecar/inspect_sqlcipher_commoncrypto.sh" "$package_dir"
fi

cleanup() {
  if [[ -n "$temporary_output" && -d "$temporary_output" ]]; then
    rm -rf "$temporary_output"
  fi
}
trap cleanup EXIT

site_packages="$(uv run --project services/core --frozen python -c 'import site; print(site.getsitepackages()[0])')"
rm -rf "$site_packages/pysqlcipher3"
cp -R "$package_dir/pysqlcipher3" "$site_packages/"

uv run --project services/core --frozen python - <<'PY'
from pysqlcipher3 import dbapi2 as db

connection = db.connect(":memory:")
try:
    if not callable(getattr(connection, "set_raw_key", None)):
        raise SystemExit("mutable-buffer SQLCipher driver method is unavailable")
    print(
        connection.execute("select sqlite_version()").fetchone()[0],
        connection.execute("pragma cipher_version").fetchone()[0],
        "mutable-buffer-key=available",
    )
finally:
    connection.close()
PY
