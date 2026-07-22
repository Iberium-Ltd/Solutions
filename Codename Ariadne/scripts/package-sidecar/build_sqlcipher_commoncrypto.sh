#!/usr/bin/env bash
# Rebuild the database binding from hash-pinned source in an empty output tree.
# Nothing from Homebrew or /usr/local is a permitted release dependency; the
# companion inspector proves architecture, deployment target, symbols, and load
# commands before this package can become a freezer input.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=versions.env
source "$SCRIPT_DIR/versions.env"

fail() {
  printf 'build failed: %s\n' "$*" >&2
  exit 1
}

usage() {
  printf 'usage: %s [EMPTY_OUTPUT_DIRECTORY]\n' "$0"
  printf 'default output: a new /tmp/ariadne-sqlcipher-package.* directory\n'
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi
[[ $# -le 1 ]] || { usage >&2; exit 2; }

if [[ $# -eq 1 ]]; then
  OUTPUT_ROOT="$1"
  mkdir -p "$OUTPUT_ROOT"
  if [[ -n "$(find "$OUTPUT_ROOT" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
    fail "output directory must be empty: $OUTPUT_ROOT"
  fi
else
  OUTPUT_ROOT="$(mktemp -d /tmp/ariadne-sqlcipher-package.XXXXXX)"
fi
OUTPUT_ROOT="$(cd "$OUTPUT_ROOT" && pwd)"

DOWNLOAD_DIR="$OUTPUT_ROOT/downloads"
SOURCE_DIR="$OUTPUT_ROOT/sources"
BUILD_DIR="$OUTPUT_ROOT/build"
PACKAGE_DIR="$OUTPUT_ROOT/package"
LOG_DIR="$OUTPUT_ROOT/logs"
mkdir -p "$DOWNLOAD_DIR" "$SOURCE_DIR" "$BUILD_DIR" "$PACKAGE_DIR" "$LOG_DIR"

on_error() {
  status=$?
  printf 'build failed with status %s; diagnostics retained at %s\n' "$status" "$OUTPUT_ROOT" >&2
  exit "$status"
}
trap on_error ERR

for command_name in awk clang cp curl find grep make patch shasum tar xcrun; do
  command -v "$command_name" >/dev/null 2>&1 || fail "missing command: $command_name"
done

[[ "$(uname -s)" == "Darwin" ]] || fail "this spike requires macOS"
[[ "$(uname -m)" == "arm64" ]] || fail "this spike requires native arm64"

PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  command -v uv >/dev/null 2>&1 || fail "uv is required when PYTHON_BIN is unset"
  PYTHON_BIN="$(uv --directory /tmp python find "$CPYTHON_VERSION")"
fi
[[ -x "$PYTHON_BIN" ]] || fail "Python is not executable: $PYTHON_BIN"

python_identity="$($PYTHON_BIN -c 'import platform; print(platform.python_version(), platform.machine())')"
case "$python_identity" in
  3.12.*\ arm64) ;;
  *) fail "CPython 3.12 arm64 required, found $python_identity" ;;
esac

SDK_ROOT="$(xcrun --sdk macosx --show-sdk-path)"
CLANG="$(xcrun --sdk macosx --find clang)"
PYTHON_INCLUDE="$($PYTHON_BIN -c 'import sysconfig; print(sysconfig.get_path("include"))')"
EXT_SUFFIX="$($PYTHON_BIN -c 'import sysconfig; print(sysconfig.get_config_var("EXT_SUFFIX"))')"
[[ "$EXT_SUFFIX" == .cpython-312-darwin.so ]] || fail "unexpected extension suffix: $EXT_SUFFIX"

BUILD_JOBS="${ARIADNE_BUILD_JOBS:-4}"
case "$BUILD_JOBS" in
  ''|*[!0-9]*) fail "ARIADNE_BUILD_JOBS must be an integer" ;;
esac
(( BUILD_JOBS >= 1 && BUILD_JOBS <= 16 )) || fail "ARIADNE_BUILD_JOBS must be between 1 and 16"

fetch_and_verify() {
  # Keep the partial suffix until TLS transfer and the pinned digest succeed so
  # an interrupted download cannot be mistaken for a reusable source archive.
  url="$1"
  expected_sha="$2"
  destination="$3"
  printf 'fetching %s\n' "$url"
  curl --fail --location --proto '=https' --tlsv1.2 --retry 3 \
    --output "$destination.part" "$url"
  mv "$destination.part" "$destination"
  printf '%s  %s\n' "$expected_sha" "$destination" | shasum -a 256 -c -
}

SQLCIPHER_ARCHIVE="$DOWNLOAD_DIR/sqlcipher-$SQLCIPHER_VERSION.tar.gz"
PYSQLCIPHER_ARCHIVE="$DOWNLOAD_DIR/pysqlcipher3-$PYSQLCIPHER3_VERSION.tar.gz"
fetch_and_verify "$SQLCIPHER_SOURCE_URL" "$SQLCIPHER_SOURCE_SHA256" "$SQLCIPHER_ARCHIVE"
fetch_and_verify "$PYSQLCIPHER3_SOURCE_URL" "$PYSQLCIPHER3_SOURCE_SHA256" "$PYSQLCIPHER_ARCHIVE"

tar -xzf "$SQLCIPHER_ARCHIVE" -C "$SOURCE_DIR"
tar -xzf "$PYSQLCIPHER_ARCHIVE" -C "$SOURCE_DIR"
SQLCIPHER_SOURCE="$SOURCE_DIR/sqlcipher-$SQLCIPHER_VERSION"
PYSQLCIPHER_SOURCE="$SOURCE_DIR/pysqlcipher3-$PYSQLCIPHER3_VERSION"

[[ "$(tr -d '[:space:]' < "$SQLCIPHER_SOURCE/VERSION")" == "$SQLCIPHER_SQLITE_VERSION" ]] || fail "SQLCipher source carries an unexpected SQLite version"
grep -Fq "CIPHER_VERSION_NUMBER $SQLCIPHER_VERSION" "$SQLCIPHER_SOURCE/src/sqlcipher.c" || fail "SQLCipher version marker is missing"
grep -Fq "VERSION = '$PYSQLCIPHER3_VERSION'" "$PYSQLCIPHER_SOURCE/setup.py" || fail "pysqlcipher3 version marker is missing"

AMALGAMATION_BUILD="$BUILD_DIR/sqlcipher-amalgamation"
mkdir -p "$AMALGAMATION_BUILD"
export MACOSX_DEPLOYMENT_TARGET
COMMON_CFLAGS="-O2 -arch arm64 -isysroot $SDK_ROOT -mmacosx-version-min=$MACOSX_DEPLOYMENT_TARGET"
SQLCIPHER_DEFINES="-DSQLITE_HAS_CODEC=1 -DSQLCIPHER_CRYPTO_CC=1 -DSQLITE_EXTRA_INIT=sqlcipher_extra_init -DSQLITE_EXTRA_SHUTDOWN=sqlcipher_extra_shutdown"

printf 'generating SQLCipher %s / SQLite %s amalgamation\n' "$SQLCIPHER_VERSION" "$SQLCIPHER_SQLITE_VERSION"
(
  cd "$AMALGAMATION_BUILD"
  CC="$CLANG" \
  CFLAGS="$COMMON_CFLAGS $SQLCIPHER_DEFINES" \
  LDFLAGS="-arch arm64 -isysroot $SDK_ROOT -mmacosx-version-min=$MACOSX_DEPLOYMENT_TARGET -framework Security -framework Foundation" \
    "$SQLCIPHER_SOURCE/configure" \
      --disable-shared \
      --enable-static \
      --with-tempstore=yes \
      --enable-fts5 > "$LOG_DIR/configure.log" 2>&1
  make -j"$BUILD_JOBS" sqlite3.c sqlite3.h > "$LOG_DIR/amalgamation.log" 2>&1
)
[[ -s "$AMALGAMATION_BUILD/sqlite3.c" && -s "$AMALGAMATION_BUILD/sqlite3.h" ]] || fail "amalgamation generation produced no source"
grep -Fq "#define SQLITE_VERSION        \"$SQLCIPHER_SQLITE_VERSION\"" "$AMALGAMATION_BUILD/sqlite3.h" || fail "generated SQLite version is wrong"

PATCHED_BINDING="$BUILD_DIR/pysqlcipher3-patched"
cp -R "$PYSQLCIPHER_SOURCE" "$PATCHED_BINDING"
patch -d "$PATCHED_BINDING" -p1 < "$SCRIPT_DIR/patches/pysqlcipher3-python312.patch" > "$LOG_DIR/binding-patch.log"

mkdir -p "$PACKAGE_DIR/pysqlcipher3" "$PACKAGE_DIR/licenses" "$BUILD_DIR/include/sqlcipher"
cp "$PATCHED_BINDING/lib/__init__.py" "$PATCHED_BINDING/lib/dbapi2.py" "$PATCHED_BINDING/lib/dump.py" "$PACKAGE_DIR/pysqlcipher3/"
cp "$AMALGAMATION_BUILD/sqlite3.h" "$BUILD_DIR/include/sqlcipher/sqlite3.h"
cp "$PYSQLCIPHER_SOURCE/LICENSE" "$PACKAGE_DIR/licenses/pysqlcipher3-LICENSE"
cp "$SQLCIPHER_SOURCE/LICENSE.md" "$PACKAGE_DIR/licenses/sqlcipher-LICENSE.md"
cp "$SQLCIPHER_SOURCE/SQLITE_LICENSE.md" "$PACKAGE_DIR/licenses/sqlite-LICENSE.md"

EXTENSION="$PACKAGE_DIR/pysqlcipher3/_sqlite3$EXT_SUFFIX"
binding_sources=("$PATCHED_BINDING"/src/python3/*.c)
compile_command=(
  "$CLANG" -bundle -undefined dynamic_lookup -O2 -arch arm64
  -isysroot "$SDK_ROOT" -mmacosx-version-min="$MACOSX_DEPLOYMENT_TARGET"
  -Wno-deprecated-declarations
  -I"$PYTHON_INCLUDE" -I"$PATCHED_BINDING/src/python3"
  -I"$BUILD_DIR/include" -I"$AMALGAMATION_BUILD"
  '-DMODULE_NAME="pysqlcipher3.dbapi2"'
  -DSQLITE_ENABLE_FTS3=1 -DSQLITE_ENABLE_FTS3_PARENTHESIS=1
  -DSQLITE_ENABLE_FTS4=1 -DSQLITE_ENABLE_FTS5=1
  -DSQLITE_ENABLE_RTREE=1 -DSQLITE_ENABLE_STAT4=1
  -DSQLITE_ENABLE_UPDATE_DELETE_LIMIT=1 -DSQLITE_SOUNDEX=1
  -DSQLITE_USE_URI=1 -DSQLITE_HAS_CODEC=1 -DSQLCIPHER_CRYPTO_CC=1
  -DSQLITE_TEMP_STORE=2 -DSQLITE_THREADSAFE=1
  -DSQLITE_EXTRA_INIT=sqlcipher_extra_init
  -DSQLITE_EXTRA_SHUTDOWN=sqlcipher_extra_shutdown
  -DHAVE_STDINT_H=1 -DSQLITE_MAX_VARIABLE_NUMBER=250000
  -DSQLITE_DEFAULT_PAGE_SIZE=4096 -DSQLITE_DEFAULT_CACHE_SIZE=-8000
  "${binding_sources[@]}" "$AMALGAMATION_BUILD/sqlite3.c"
  -framework Security -framework Foundation -lm -o "$EXTENSION"
)

printf 'building pysqlcipher3 %s CPython 3.12 arm64 extension\n' "$PYSQLCIPHER3_VERSION"
printf '%q ' "${compile_command[@]}" > "$LOG_DIR/clang-command.log"
printf '\n' >> "$LOG_DIR/clang-command.log"
"${compile_command[@]}" > "$LOG_DIR/clang.log" 2>&1
[[ -s "$EXTENSION" ]] || fail "compiler produced no extension"

"$SCRIPT_DIR/inspect_sqlcipher_commoncrypto.sh" "$PACKAGE_DIR" "$PYTHON_BIN" \
  | tee "$LOG_DIR/inspection.log"

extension_sha256="$(shasum -a 256 "$EXTENSION" | awk '{print $1}')"
{
  printf 'sqlcipher_version=%s\n' "$SQLCIPHER_VERSION"
  printf 'sqlcipher_tag=%s\n' "$SQLCIPHER_TAG"
  printf 'sqlcipher_commit=%s\n' "$SQLCIPHER_COMMIT"
  printf 'sqlcipher_source_sha256=%s\n' "$SQLCIPHER_SOURCE_SHA256"
  printf 'sqlite_version=%s\n' "$SQLCIPHER_SQLITE_VERSION"
  printf 'pysqlcipher3_version=%s\n' "$PYSQLCIPHER3_VERSION"
  printf 'pysqlcipher3_source_sha256=%s\n' "$PYSQLCIPHER3_SOURCE_SHA256"
  printf 'python=%s\n' "$python_identity"
  printf 'macos_deployment_target=%s\n' "$MACOSX_DEPLOYMENT_TARGET"
  printf 'crypto_provider=CommonCrypto\n'
  printf 'extension_sha256=%s\n' "$extension_sha256"
} > "$OUTPUT_ROOT/BUILD-MANIFEST.txt"

trap - ERR
printf 'build and inspection passed\n'
printf 'OUTPUT_ROOT=%s\n' "$OUTPUT_ROOT"
printf 'PACKAGE_DIR=%s\n' "$PACKAGE_DIR"
printf 'EXTENSION=%s\n' "$EXTENSION"
