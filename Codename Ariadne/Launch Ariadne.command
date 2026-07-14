#!/bin/zsh
set -euo pipefail

project_root="$(cd -- "$(dirname -- "$0")" && pwd)"
app="$project_root/apps/desktop/src-tauri/target/release/bundle/macos/Codename Ariadne.app"

if [[ ! -d "$app" ]]; then
  print -u2 "Codename Ariadne.app was not found. Rebuild the packaged app first."
  read -r "?Press Return to close."
  exit 1
fi

open "$app"
