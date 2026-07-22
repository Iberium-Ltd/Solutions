#!/usr/bin/env bash
# Verify the exact extension that freezing will consume. Runtime SQLCipher/FTS/
# JSON checks complement Mach-O inspection; neither alone proves encrypted
# database support is present and loadable on the target macOS floor.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=versions.env
source "$SCRIPT_DIR/versions.env"

fail() {
  printf 'inspection failed: %s\n' "$*" >&2
  exit 1
}

if [[ $# -lt 1 || $# -gt 2 ]]; then
  printf 'usage: %s PACKAGE_DIR [PYTHON_BIN]\n' "$0" >&2
  exit 2
fi

PACKAGE_DIR="$(cd "$1" && pwd)"
PYTHON_BIN="${2:-${PYTHON_BIN:-}}"

if [[ -z "$PYTHON_BIN" ]]; then
  command -v uv >/dev/null 2>&1 || fail "uv is required when PYTHON_BIN is unset"
  PYTHON_BIN="$(uv --directory /tmp python find "$CPYTHON_VERSION")"
fi
[[ -x "$PYTHON_BIN" ]] || fail "Python is not executable: $PYTHON_BIN"

for command_name in file lipo nm otool vtool shasum; do
  command -v "$command_name" >/dev/null 2>&1 || fail "missing command: $command_name"
done

extension_count="$(find "$PACKAGE_DIR/pysqlcipher3" -maxdepth 1 -type f -name '_sqlite3*.so' | wc -l | tr -d ' ')"
[[ "$extension_count" == "1" ]] || fail "expected one DB-API extension, found $extension_count"
EXTENSION="$(find "$PACKAGE_DIR/pysqlcipher3" -maxdepth 1 -type f -name '_sqlite3*.so' -print -quit)"

file_output="$(file "$EXTENSION")"
printf '%s\n' "$file_output"
grep -Fq 'Mach-O 64-bit bundle arm64' <<<"$file_output" || fail "extension is not an arm64 Mach-O bundle"

architectures="$(lipo -archs "$EXTENSION")"
[[ "$architectures" == "arm64" ]] || fail "unexpected architectures: $architectures"

load_commands="$(otool -L "$EXTENSION")"
printf '%s\n' "$load_commands"
grep -Fq 'Security.framework' <<<"$load_commands" || fail "Security.framework is not linked"
if grep -Eiq '/opt/homebrew|/usr/local|libcrypto|libssl|libsqlcipher|libsqlite' <<<"$load_commands"; then
  fail "extension has a forbidden non-system database or crypto dependency"
fi

commoncrypto_symbols="$(nm -u "$EXTENSION")"
grep -Fq '_CCCryptorCreate' <<<"$commoncrypto_symbols" || fail "CommonCrypto cipher symbols are absent"
grep -Fq '_CCHmacInit' <<<"$commoncrypto_symbols" || fail "CommonCrypto HMAC symbols are absent"
grep -Fq '_CCKeyDerivationPBKDF' <<<"$commoncrypto_symbols" || fail "CommonCrypto PBKDF symbols are absent"

build_version="$(vtool -show-build "$EXTENSION")"
printf '%s\n' "$build_version"
minimum_os="$(awk '$1 == "minos" { print $2; exit }' <<<"$build_version")"
[[ "$minimum_os" == "$MACOSX_DEPLOYMENT_TARGET" ]] || fail "expected minOS $MACOSX_DEPLOYMENT_TARGET, found $minimum_os"

"$PYTHON_BIN" "$SCRIPT_DIR/runtime_probe.py" \
  "$PACKAGE_DIR" "$SQLCIPHER_VERSION" "$SQLCIPHER_MIN_SQLITE_VERSION"

artifact_sha256="$(shasum -a 256 "$EXTENSION" | awk '{print $1}')"
printf 'inspection passed\n'
printf 'extension=%s\n' "$EXTENSION"
printf 'sha256=%s\n' "$artifact_sha256"
printf 'architecture=%s\n' "$architectures"
printf 'minos=%s\n' "$minimum_os"
