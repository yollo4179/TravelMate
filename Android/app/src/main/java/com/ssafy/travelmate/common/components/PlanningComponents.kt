package com.ssafy.travelmate.common.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Place
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import com.ssafy.travelmate.data.remote.dto.responses.place.PlaceSearchResponse

@Composable
fun PlanningSection(
    title: String,
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit
) {
    Surface(
        modifier = modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surfaceVariant,
        shape = RoundedCornerShape(16.dp)
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(title, style = MaterialTheme.typography.titleSmall)
            content()
        }
    }
}

@Composable
fun PlanningError(message: String?) {
    if (message == null) return
    Surface(color = MaterialTheme.colorScheme.errorContainer, shape = RoundedCornerShape(12.dp)) {
        Text(
            message,
            modifier = Modifier.fillMaxWidth().padding(12.dp),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onErrorContainer
        )
    }
}

@Composable
fun PlaceResultCard(
    place: PlaceSearchResponse,
    selected: Boolean,
    onSelect: () -> Unit,
    action: @Composable (() -> Unit)? = null
) {
    OutlinedCard(
        onClick = onSelect,
        modifier = Modifier.fillMaxWidth().testTag("place-${place.placeId}").semantics { this.selected = selected },
        shape = RoundedCornerShape(14.dp),
        border = BorderStroke(1.dp, if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outlineVariant),
        colors = CardDefaults.outlinedCardColors(
            containerColor = if (selected) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surface
        )
    ) {
        Row(
            Modifier.padding(12.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Surface(
                modifier = Modifier.size(64.dp),
                shape = RoundedCornerShape(10.dp),
                color = MaterialTheme.colorScheme.surfaceVariant
            ) {
                if (place.imageUrl.isNullOrBlank()) {
                    Box(contentAlignment = Alignment.Center) {
                        Icon(Icons.Default.Place, null, tint = MaterialTheme.colorScheme.primary)
                    }
                } else {
                    AsyncImage(
                        model = place.imageUrl,
                        contentDescription = null,
                        contentScale = ContentScale.Crop,
                        modifier = Modifier.fillMaxSize()
                    )
                }
            }
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(place.name, style = MaterialTheme.typography.titleSmall)
                Text(
                    listOfNotNull(place.city, place.category).joinToString(" · "),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Text("운영시간 확인 필요", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.error)
            }
            action?.invoke()
        }
    }
}
