package mx.orvia.campo.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

val Forest = Color(0xFF00875E)
val Dark = Color(0xFF172B2A)
val Muted = Color(0xFF677B77)
val Canvas = Color(0xFFF5F8F7)
val Border = Color(0xFFE3EBE8)
val EmeraldSoft = Color(0xFFE4F5EF)
val Amber = Color(0xFF9D6B14)

private val scheme = lightColorScheme(
    primary = Forest, onPrimary = Color.White,
    primaryContainer = EmeraldSoft, onPrimaryContainer = Dark,
    background = Canvas, onBackground = Dark,
    surface = Color.White, onSurface = Dark,
    surfaceVariant = Color(0xFFEDF2F0), onSurfaceVariant = Muted,
    outline = Border, error = Color(0xFFB44242)
)

@Composable fun OrviaTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = scheme, content = content)
}
