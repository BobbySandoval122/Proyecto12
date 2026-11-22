#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
url='https://raw.githubusercontent.com/gradle/gradle/v8.13.0/gradle/wrapper/gradle-wrapper.jar'
curl --fail --location --retry 2 "$url" -o gradle/wrapper/gradle-wrapper.jar
[ "$(wc -c < gradle/wrapper/gradle-wrapper.jar)" -gt 10000 ] || { echo 'Descarga incompleta' >&2; exit 1; }
echo 'Wrapper listo. Ejecuta ./gradlew assembleDebug.'
