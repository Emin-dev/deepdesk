#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUTPUT="${1:?Usage: run-ui-tests.sh ABSOLUTE_NEW_OUTPUT_DIRECTORY}"
[[ "$(uname -s)" == Darwin ]] || { echo 'Requires macOS with Xcode.' >&2; exit 1; }
[[ "$OUTPUT" == /* && ! -e "$OUTPUT" ]] || { echo 'Output must be a new absolute path.' >&2; exit 1; }
mkdir -p "$OUTPUT"
python3 "$ROOT/UIHarness/generate_project.py"
/usr/bin/xcrun xcodebuild test \
  -project "$ROOT/UIHarness/DeepdeskUITests.xcodeproj" \
  -scheme DeepdeskUITestHost \
  -destination 'platform=macOS,arch=arm64' \
  -derivedDataPath "$OUTPUT/DerivedData" \
  -resultBundlePath "$OUTPUT/SyntheticUI.xcresult" \
  -parallel-testing-enabled NO \
  -maximum-concurrent-test-simulator-destinations 1 \
  CODE_SIGN_IDENTITY=- \
  | tee "$OUTPUT/xcodebuild.log"
