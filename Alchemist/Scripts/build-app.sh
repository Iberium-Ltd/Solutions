#!/bin/zsh
set -euo pipefail

script_dir="${0:A:h}"
project_dir="${script_dir:h}"
cd "$project_dir"

swift build -c release
bin_dir="$(swift build -c release --show-bin-path)"
app_dir="$project_dir/Build/Alchemist.app"

rm -rf "$app_dir"
mkdir -p "$app_dir/Contents/MacOS" "$app_dir/Contents/Resources"
cp "$bin_dir/Alchemist" "$app_dir/Contents/MacOS/Alchemist"
cp "$project_dir/Resources/Info.plist" "$app_dir/Contents/Info.plist"
cp "$project_dir/Resources/Alchemist.icns" "$app_dir/Contents/Resources/Alchemist.icns"

# An ad-hoc signature makes the locally-built bundle launch cleanly on macOS.
if command -v codesign >/dev/null 2>&1; then
  codesign --force --sign - "$app_dir"
fi

echo "Built $app_dir"
