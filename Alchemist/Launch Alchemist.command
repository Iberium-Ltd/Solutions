#!/bin/zsh
set -euo pipefail

project_dir="${0:A:h}"
app_path="$project_dir/Build/Alchemist.app"

if [[ ! -d "$app_path" ]]; then
  "$project_dir/Scripts/build-app.sh"
fi

open "$app_path"
