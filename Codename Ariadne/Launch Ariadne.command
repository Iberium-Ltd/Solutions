#!/bin/zsh
# User-facing launcher for the already-built macOS bundle; it never starts a
# development server or silently rebuilds binaries.
set -euo pipefail

project_root="$(cd -- "$(dirname -- "$0")" && pwd)"
app="$project_root/apps/desktop/src-tauri/target/release/bundle/macos/Codename Ariadne.app"
ollama_models="/Volumes/Predator SSD GM7000/LLMs/Ollama/models"

if [[ ! -d "$app" ]]; then
  print -u2 "Codename Ariadne.app was not found. Rebuild the packaged app first."
  read -r "?Press Return to close."
  exit 1
fi

# Ollama owns model storage; Ariadne connects only to its loopback API. Keep the
# GUI runtime pointed at the SSD store and start it when available. The symlink
# at ~/.ollama/models remains the fallback for shells and existing tooling.
if [[ -d "$ollama_models" ]]; then
  launchctl setenv OLLAMA_MODELS "$ollama_models" >/dev/null 2>&1 || true
  if ! pgrep -f "/Applications/Ollama.app/Contents/Resources/ollama serve" >/dev/null; then
    open -a Ollama
  fi
else
  print -u2 "Ollama model store is unavailable at: $ollama_models"
  print -u2 "Ariadne will still open; local-AI runs will report the runtime as unavailable."
fi

open "$app"
