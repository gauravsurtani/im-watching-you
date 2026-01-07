package com.lifelogger.android.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.lifelogger.android.LifeloggerApp
import com.lifelogger.android.data.AppUsageSummary
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

@Composable
fun MainScreen(
    onRequestPermissions: () -> Unit,
    hasUsagePermission: () -> Boolean
) {
    val context = LocalContext.current
    val app = context.applicationContext as LifeloggerApp

    val trackingEnabled by app.settingsRepository.trackingEnabled.collectAsState(initial = false)
    val deviceId by app.settingsRepository.deviceId.collectAsState(initial = "")
    val unsyncedCount by app.database.activityEventDao().getUnsyncedCount().collectAsState(initial = 0)
    val totalCount by app.database.activityEventDao().getTotalCount().collectAsState(initial = 0)
    val lastSync by app.settingsRepository.lastSyncTime.collectAsState(initial = 0L)

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
    ) {
        // Header
        Text(
            text = "Lifelogger",
            style = MaterialTheme.typography.headlineLarge
        )

        Text(
            text = "Privacy-first activity tracking",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )

        Spacer(modifier = Modifier.height(24.dp))

        // Status Card
        Card(
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.surfaceVariant
            )
        ) {
            Column(modifier = Modifier.padding(16.dp)) {
                Text(
                    text = "Status",
                    style = MaterialTheme.typography.titleMedium
                )

                Spacer(modifier = Modifier.height(8.dp))

                StatusRow("Device ID", deviceId.ifEmpty { "Generating..." })
                StatusRow("Total Events", totalCount.toString())
                StatusRow("Pending Sync", unsyncedCount.toString())
                StatusRow("Last Sync", formatTimestamp(lastSync))
            }
        }

        Spacer(modifier = Modifier.height(16.dp))

        // Controls Card
        Card(
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.surfaceVariant
            )
        ) {
            Column(modifier = Modifier.padding(16.dp)) {
                Text(
                    text = "Controls",
                    style = MaterialTheme.typography.titleMedium
                )

                Spacer(modifier = Modifier.height(8.dp))

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text("Activity Tracking")
                    Switch(
                        checked = trackingEnabled,
                        onCheckedChange = { /* Toggle tracking */ }
                    )
                }

                Spacer(modifier = Modifier.height(8.dp))

                if (!hasUsagePermission()) {
                    Button(
                        onClick = onRequestPermissions,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text("Grant Permissions")
                    }
                }

                Button(
                    onClick = { /* Trigger sync */ },
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text("Sync Now")
                }
            }
        }

        Spacer(modifier = Modifier.height(16.dp))

        // Top Apps Card
        Text(
            text = "Top Apps Today",
            style = MaterialTheme.typography.titleMedium
        )

        Spacer(modifier = Modifier.height(8.dp))

        TopAppsList()
    }
}

@Composable
private fun StatusRow(label: String, value: String) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp),
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(
            text = label,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Text(text = value)
    }
}

@Composable
private fun TopAppsList() {
    val context = LocalContext.current
    val app = context.applicationContext as LifeloggerApp

    // Get today's start timestamp
    val todayStart = remember {
        val cal = java.util.Calendar.getInstance()
        cal.set(java.util.Calendar.HOUR_OF_DAY, 0)
        cal.set(java.util.Calendar.MINUTE, 0)
        cal.set(java.util.Calendar.SECOND, 0)
        cal.timeInMillis
    }

    val topApps by produceTopApps(app, todayStart).collectAsState(initial = emptyList())

    if (topApps.isEmpty()) {
        Card(
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.surfaceVariant
            )
        ) {
            Text(
                text = "No activity data yet",
                modifier = Modifier.padding(16.dp),
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    } else {
        LazyColumn {
            items(topApps) { app ->
                AppUsageItem(app)
            }
        }
    }
}

@Composable
private fun produceTopApps(app: LifeloggerApp, since: Long): Flow<List<AppUsageSummary>> {
    return remember(since) {
        flow {
            val apps = app.database.activityEventDao().getTopApps(since, 10)
            emit(apps)
        }
    }
}

@Composable
private fun AppUsageItem(app: AppUsageSummary) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surface
        )
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column {
                Text(
                    text = app.appName ?: "Unknown",
                    style = MaterialTheme.typography.bodyLarge
                )
                Text(
                    text = "${app.eventCount} sessions",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            Text(
                text = formatDuration(app.totalSeconds),
                style = MaterialTheme.typography.titleMedium
            )
        }
    }
}

private fun formatTimestamp(timestamp: Long): String {
    if (timestamp == 0L) return "Never"
    val sdf = SimpleDateFormat("MMM d, HH:mm", Locale.getDefault())
    return sdf.format(Date(timestamp))
}

private fun formatDuration(seconds: Double): String {
    val hours = (seconds / 3600).toInt()
    val minutes = ((seconds % 3600) / 60).toInt()
    return when {
        hours > 0 -> "${hours}h ${minutes}m"
        else -> "${minutes}m"
    }
}
