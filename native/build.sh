#!/bin/zsh
set -euo pipefail

ROOT="${0:A:h:h}"
APP="$ROOT/.build/Laya.app"
MACOS="$APP/Contents/MacOS"
rm -rf "$ROOT/.build/LayaSpeech.app"  # the helper's old name
mkdir -p "$MACOS"
cp "$ROOT/native/Info.plist" "$APP/Contents/Info.plist"
swiftc "$ROOT"/native/Laya/*.swift \
  -framework AppKit -framework AVFoundation -framework CoreGraphics -framework Network -framework QuartzCore -framework Speech \
  -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker "$ROOT/native/Info.plist" \
  -o "$MACOS/Laya"
# Keep the ad-hoc development build's designated requirement stable across recompiles. Without an
# explicit requirement, codesign falls back to the binary's changing cdhash and macOS forgets the
# Accessibility/Input Monitoring grant after every build.
codesign --force --sign - \
  --requirements '=designated => identifier "dev.aryan.laya"' \
  "$APP" >/dev/null
echo "$APP"
