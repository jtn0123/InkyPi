#!/usr/bin/env bash
# Contact sheet of the whole app from headless Chrome, at the tablet's CSS geometry.
#   sim/shoot.sh <outdir> [scene ...]
# Starts sim/server.py if nothing answers on :8788, shoots the dashboard and every panel
# for each scene (default: the real weather plus rain, snow, storm, fog, clear-night),
# and writes <outdir>/<scene>-<screen>.png. Needs Google Chrome.
set -euo pipefail
OUT="${1:?outdir}"; shift || true
SCENES=("$@"); [ ${#SCENES[@]} -eq 0 ] && SCENES=(real rain snow storm fog clear-night)
CH="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
URL="http://127.0.0.1:8788"
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$OUT"
if ! curl -sf -o /dev/null "$URL/"; then
  (python3 "$HERE/server.py" >/dev/null 2>&1 &) ; sleep 1.2
fi
SCREENS=(home clock weather hourly daily sensors timer system settings moon air year calendar paper gallery news)

# EVERY SHOT IS CHECKED BEFORE IT IS KEPT, and re-taken if it is the wrong picture.
# Five of one hand-off's thirty-six files were the dashboard filed under a panel's name or
# an empty sky: `?open=` is driven by script, and a headless screenshot is taken on a clock
# that does not wait for one. check-shot.py looks for the panel title in the top-left band,
# which is the one mark the dashboard never has there. Shooting again costs two seconds.
shoot() {  # shoot <url> <file> <home|panel>
  local try
  for try in 1 2 3; do
    # 20s of virtual time, not 9: the icon set carries always-on CSS animations, and every
    # frame they ask for advances headless Chrome's virtual clock — so a page could burn
    # the whole budget during boot and be captured before its scripts had finished.
    # --run-all-compositor-stages-before-draw: without it the capture can be taken from a
    # frame the compositor has not finished, which is the empty-sky shot.
    "$CH" --headless=new --disable-gpu --hide-scrollbars --window-size=711,1138 \
      --run-all-compositor-stages-before-draw \
      --virtual-time-budget=$((20000 * try)) --screenshot="$2" "$1" >/dev/null 2>&1 || true
    if python3 "$HERE/check-shot.py" "$2" "$3" >/dev/null 2>&1; then return 0; fi
  done
  echo "BAD SHOT after 3 tries: $2"
}

for sc in "${SCENES[@]}"; do
  q=""; [ "$sc" != "real" ] && q="scene=$sc"
  for scr in "${SCREENS[@]}"; do
    if [ "$scr" = "home" ]; then p="$URL/?$q"; else p="$URL/?open=$scr&$q"; fi
    # panels other than weather ones look the same in every scene: shoot them once
    if [ "$sc" != "real" ] && [[ ! "$scr" =~ ^(home|weather|hourly|daily)$ ]]; then continue; fi
    if [ "$scr" = "home" ]; then shoot "$p" "$OUT/$sc-$scr.png" home
    else shoot "$p" "$OUT/$sc-$scr.png" panel; fi
  done
done
echo "shots in $OUT: $(find "$OUT" -maxdepth 1 -type f -name '*.png' | wc -l | tr -d ' ')"
