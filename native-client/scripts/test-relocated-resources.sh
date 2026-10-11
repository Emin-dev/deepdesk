#!/bin/bash
set -euo pipefail
# Native-only packaging check. Never launches Deepdesk, helpers, Keychain, or model downloads.
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
OUTPUT="${1:-}"
if [[ "$(uname -s)" != Darwin || "$OUTPUT" != /* || -e "$OUTPUT" || -L "$OUTPUT" ]]; then
  echo 'Usage on macOS: test-relocated-resources.sh NEW_ABSOLUTE_OUTPUT_DIRECTORY' >&2
  exit 64
fi
mkdir -p "$OUTPUT"
OUTPUT="$(cd "$OUTPUT" && pwd -P)"
case "$OUTPUT/" in "$ROOT/.build/"*) echo 'Output cannot be inside .build.' >&2; exit 64;; esac
cd "$ROOT"
./scripts/build-app.sh "$OUTPUT/original"
swift build --configuration release --arch arm64 --product DeepdeskResourceSmoke
BIN_PATH="$(swift build --configuration release --arch arm64 --show-bin-path)"
ACCESSOR="$BIN_PATH/Deepdesk.build/DerivedSources/resource_bundle_accessor.swift"
if [[ ! -f "$ACCESSOR" || -L "$ACCESSOR" || "$(wc -c < "$ACCESSOR")" -gt 16384 ]]; then
  echo 'Expected bounded current-toolchain generated accessor was not found.' >&2
  exit 1
fi
echo 'DEEPDESK_GENERATED_RESOURCE_ACCESSOR_BEGIN'
swift --version
shasum -a 256 "$ACCESSOR"
cat "$ACCESSOR"
echo 'DEEPDESK_GENERATED_RESOURCE_ACCESSOR_END'

PROBE="$OUTPUT/DeepdeskResourceSmoke"
cp "$BIN_PATH/DeepdeskResourceSmoke" "$PROBE"
mkdir "$OUTPUT/relocated"
APP="$OUTPUT/relocated/Deepdesk.app"
mv "$OUTPUT/original/Deepdesk.app" "$APP"
RESOURCE="$APP/Contents/Resources/Deepdesk_Deepdesk.bundle"
HIDDEN_RESOURCE="$OUTPUT/hidden-packaged-resource.bundle"
HIDDEN_BUILD="$OUTPUT/hidden-build"

restore() {
  local status=$?
  trap - EXIT
  if [[ -e "$HIDDEN_RESOURCE" ]]; then
    if [[ -e "$RESOURCE" || -L "$RESOURCE" ]]; then status=1
    else mv "$HIDDEN_RESOURCE" "$RESOURCE" || status=1; fi
  fi
  if [[ -e "$HIDDEN_BUILD" ]]; then
    if [[ -e "$ROOT/.build" || -L "$ROOT/.build" ]]; then status=1
    else mv "$HIDDEN_BUILD" "$ROOT/.build" || status=1; fi
  fi
  exit "$status"
}
trap restore EXIT
if [[ ! -d "$ROOT/.build" || -L "$ROOT/.build" ]]; then
  echo 'Expected an owned regular build directory.' >&2
  exit 1
fi
# Break every generated absolute .build fallback while retaining reversible CI build outputs.
mv "$ROOT/.build" "$HIDDEN_BUILD"
[[ ! -e "$ROOT/.build" && ! -e "$OUTPUT/original/Deepdesk.app" ]]
"$PROBE" "$APP"
echo 'DEEPDESK_RELOCATION_CHECK original-app-absent build-path-absent catalog-loaded'

mv "$RESOURCE" "$HIDDEN_RESOURCE"
set +e
"$PROBE" "$APP"
missing_status=$?
set -e
if [[ "$missing_status" -ne 2 ]]; then
  echo 'Missing packaged resource did not produce the expected clean failure.' >&2
  exit 1
fi
echo 'DEEPDESK_RELOCATION_CHECK missing-packaged-resource-rejected'
mv "$HIDDEN_RESOURCE" "$RESOURCE"
"$PROBE" "$APP"
echo 'DEEPDESK_RELOCATION_CHECK restored-packaged-resource-loaded'
