@echo off
setlocal
cd /d "%~dp0"
if not exist "gradle\wrapper\gradle-wrapper.jar" (
  echo Falta gradle-wrapper.jar. Ejecuta preparar-wrapper.ps1 con PowerShell.
  exit /b 1
)
if defined JAVA_HOME (
  "%JAVA_HOME%\bin\java.exe" -classpath "gradle\wrapper\gradle-wrapper.jar" org.gradle.wrapper.GradleWrapperMain %*
) else (
  java -classpath "gradle\wrapper\gradle-wrapper.jar" org.gradle.wrapper.GradleWrapperMain %*
)
exit /b %ERRORLEVEL%
