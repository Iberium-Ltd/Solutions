#!/bin/zsh
# User-facing launcher for the already-built macOS bundle; it never starts a
# development server or silently rebuilds binaries.
set -euo pipefail

project_root="$(cd -- "$(dirname -- "$0")" && pwd)"
app="$project_root/apps/desktop/src-tauri/target/release/bundle/macos/Codename Ariadne.app"

if [[ ! -d "$app" ]]; then
  print -u2 "Codename Ariadne.app was not found. Rebuild the packaged app first."
  read -r "?Press Return to close."
  exit 1
fi

open "$app"
