#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUTPUT="${1:-$ROOT/dist}"
if [[ "$(uname -s)" != Darwin ]]; then
  echo 'Deepdesk.app must be built on macOS with Xcode 26 or later.' >&2
  exit 1
fi
if ! xcrun --find swift >/dev/null 2>&1; then
  echo 'Xcode command-line tools are required.' >&2
  exit 1
fi
mkdir -p "$OUTPUT"
OUTPUT="$(cd "$OUTPUT" && pwd)"
APP="$OUTPUT/Deepdesk.app"
if [[ -e "$APP" ]]; then
  echo "Refusing to overwrite an existing app bundle: $APP" >&2
  exit 1
fi
cd "$ROOT"
swift test
swift build --configuration release --arch arm64
BIN_PATH="$(swift build --configuration release --arch arm64 --show-bin-path)"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$APP/Contents/Helpers"
cp "$BIN_PATH/Deepdesk" "$APP/Contents/MacOS/Deepdesk"
cp "$ROOT/Resources/Info.plist" "$APP/Contents/Info.plist"
RESOURCE_BUNDLE="$BIN_PATH/Deepdesk_Deepdesk.bundle"
if [[ -d "$RESOURCE_BUNDLE" ]]; then
  cp -R "$RESOURCE_BUNDLE" "$APP/Contents/Resources/"
else
  echo "Missing SwiftPM resource bundle: $RESOURCE_BUNDLE" >&2
  exit 1
fi
chmod 755 "$APP/Contents/MacOS/Deepdesk"
/usr/bin/plutil -lint "$APP/Contents/Info.plist"
echo "$APP"
echo 'Native app bundle built. The Python helper, signing, notarization, and DMG packaging are separate required stages.' >&2
