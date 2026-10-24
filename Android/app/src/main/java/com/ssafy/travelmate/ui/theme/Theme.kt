package com.ssafy.travelmate.ui.theme

import android.app.Activity
import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext

private val DarkColorScheme = darkColorScheme(
    /*primary = Purple80,
    secondary = PurpleGrey80,
    tertiary = Pink80*/
    primary = theme_dark_main_sky,
    onPrimary = Color.White,
    secondary = theme_dark_sub_sky,
    surface = theme_dark_surface,
    onSurface = theme_dark_text,
    primaryContainer = Color(0xFF123D60),
    onPrimaryContainer = Color(0xFFD5EBFF),
    secondaryContainer = Color(0xFF183244),
    onSecondaryContainer = Color(0xFFD5EBFF),
    surfaceVariant = Color(0xFF203444),
    onSurfaceVariant = Color(0xFFB4C9DA),
    outlineVariant = Color(0xFF3B5366),
    onBackground = theme_dark_text,
    background = theme_dark_sub_sky

)

private val LightColorScheme = lightColorScheme(
    /*primary = Purple40,
    secondary = PurpleGrey40,
    tertiary = Pink40*/

    primary = Color(0xFF0878F9),
    onPrimary = Color.White,
    secondary = theme_light_sub_sky,  //버튼 색껄
    surface = theme_light_surface,
    onSurface = theme_light_text,
    primaryContainer = Color(0xFFE5F2FF),
    onPrimaryContainer = Color(0xFF064C9A),
    secondaryContainer = Color(0xFFEAF5FF),
    onSecondaryContainer = Color(0xFF214A70),
    surfaceVariant = Color(0xFFF2F8FF),
    onSurfaceVariant = Color(0xFF62758D),
    outline = Color(0xFF9DB5D0),
    outlineVariant = Color(0xFFD5E2F1),
    onBackground = Color(0xFF10243D),
    background = theme_light_sub_sky


    /* Other default colors to override
    background = Color(0xFFFFFBFE),
    surface = Color(0xFFFFFBFE),
    onPrimary = Color.White,
    onSecondary = Color.White,
    onTertiary = Color.White,
    onBackground = Color(0xFF1C1B1F),
    onSurface = Color(0xFF1C1B1F),
    */
)

@Composable
fun TravelMateTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    // Dynamic color is available on Android 12+
    dynamicColor: Boolean = true,
    content: @Composable () -> Unit
) {
    val colorScheme = when {
        dynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> {
            val context = LocalContext.current
            if (darkTheme) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        }

        darkTheme -> DarkColorScheme
        else -> LightColorScheme
    }

    MaterialTheme(
        colorScheme = colorScheme,
        typography = Typography,
        content = content
    )
}
