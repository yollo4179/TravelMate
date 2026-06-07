package com.ssafy.travelmate.util.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Brush
import com.ssafy.travelmate.ui.theme.*

class UtilTheme {

    @Composable
    fun generateGradientBackground(): Brush {
        val isDark = isSystemInDarkTheme()
        
        return Brush.verticalGradient(
                colors = listOf( MaterialTheme.colorScheme.secondary, MaterialTheme.colorScheme.primary))

    }
}
