#!/bin/sh
set -eu
package_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
"$package_dir/Homeboard/Homeboard" --install
printf '\nHomeboard is installed. Open it from your application menu.\n'
printf 'Start automatically after you sign in? [y/N] '
if [ -t 0 ]; then
  read -r startup_choice
  case "$startup_choice" in
    y|Y|yes|Yes) "$HOME/.local/opt/homeboard/current/Homeboard" --enable-startup ;;
  esac
fi
