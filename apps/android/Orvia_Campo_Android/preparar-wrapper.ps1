$ErrorActionPreference = 'Stop'
$uri = 'https://raw.githubusercontent.com/gradle/gradle/v8.13.0/gradle/wrapper/gradle-wrapper.jar'
$out = Join-Path $PSScriptRoot 'gradle\wrapper\gradle-wrapper.jar'
Write-Host 'Descargando el Gradle Wrapper desde el repositorio oficial de Gradle...'
Invoke-WebRequest -Uri $uri -OutFile $out
if ((Get-Item $out).Length -lt 10000) { throw 'Descarga incompleta' }
Write-Host 'Listo. Abre la carpeta en Android Studio o ejecuta .\gradlew.bat assembleDebug'
