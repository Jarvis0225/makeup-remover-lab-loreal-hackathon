#!/bin/bash
# 用 Keynote 把 pptx 渲染为逐页 PNG（视觉 QA 用）：bash docs/render_slides.sh <pptx> <输出目录>
set -e
IN="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
OUT="$2"; mkdir -p "$OUT"; OUT="$(cd "$OUT" && pwd)"
osascript <<EOF
tell application "Keynote"
  set d to open POSIX file "$IN"
  delay 2
  export d to POSIX file "$OUT" as slide images with properties {image format:PNG, skipped slides:false}
  close d saving no
end tell
EOF
ls "$OUT"
