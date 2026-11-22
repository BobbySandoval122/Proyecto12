# Identidad visual Orvia

Se incorporo la imagen oficial proporcionada por el equipo.

- `app/src/main/res/drawable/orvia_logo.png`: logotipo usado en la cabecera y la pantalla de login.
- `app/src/main/res/drawable/orvia_launcher_mark.png`: simbolo de Orvia centrado en el icono adaptativo.
- `app/src/main/res/mipmap-anydpi-v26/ic_launcher.xml`: usa la nueva marca; fondo blanco.
- `app/src/main/java/mx/orvia/campo/ui/Screens.kt`: solo cambios en la presentacion del logo.

No se cambiaron llamadas REST, permisos, GPS, registros offline, evidencias, autenticacion ni modelos de datos.

## Instalar

1. Extrae el ZIP.
2. En Android Studio usa File > Open y elige la carpeta Orvia_Campo_Android.
3. Sincroniza Gradle y ejecuta app. Si reemplazas una carpeta previa, conserva un respaldo.
4. Comprueba el encabezado, pantalla de inicio de sesion e icono del launcher.

La imagen original compartida tiene baja resolucion; el logo se escalo para recursos graficos,
pero para una version de publicacion conviene solicitar el logotipo oficial en SVG/PNG de alta resolucion.
