#!/bin/zsh
set -euo pipefail

script_dir="${0:A:h}"
project_dir="${script_dir:h}"
smoke_dir="$(mktemp -d)"
trap 'rm -rf "$smoke_dir"' EXIT

swiftc -parse-as-library \
  "$project_dir/Sources/Alchemist/Domain/Models.swift" \
  "$project_dir/Sources/Alchemist/Services/MediaProbe.swift" \
  "$project_dir/Sources/Alchemist/Services/OutputPlanner.swift" \
  "$project_dir/Sources/Alchemist/Services/TranscodeEngine.swift" \
  "$project_dir/Scripts/TranscodeSmoke.swift" \
  -framework AppKit \
  -framework AVFoundation \
  -framework VideoToolbox \
  -framework CoreMedia \
  -framework CoreVideo \
  -framework AudioToolbox \
  -o "$smoke_dir/alchemist-smoke"

"$smoke_dir/alchemist-smoke"
