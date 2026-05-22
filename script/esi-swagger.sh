#!/usr/bin/env bash
# Downloads the latest EVE ESI OpenAPI spec to docs/esi-swagger.json
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT="$REPO_ROOT/docs/esi-swagger.json"

mkdir -p "$(dirname "$OUTPUT")"

echo "Downloading ESI swagger spec..."
curl -fSL "https://esi.evetech.net/latest/swagger.json" -o "$OUTPUT"

echo "Saved to $OUTPUT ($(wc -c < "$OUTPUT" | tr -d ' ') bytes)"
