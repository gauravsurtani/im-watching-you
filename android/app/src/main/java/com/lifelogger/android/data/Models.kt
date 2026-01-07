package com.lifelogger.android.data

import androidx.room.Entity
import androidx.room.PrimaryKey
import kotlinx.serialization.Serializable

/**
 * Activity event stored locally before sync.
 * Matches the server-side ActivityEvent model.
 */
@Entity(tableName = "activity_events")
@Serializable
data class ActivityEvent(
    @PrimaryKey(autoGenerate = true)
    val id: Long = 0,

    val timestamp: Long, // Unix timestamp in milliseconds

    val deviceId: String,

    val source: String, // "android_usage", "android_accessibility", "android_audio"

    val appName: String? = null,

    val windowTitle: String? = null, // Accessibility-derived

    val packageName: String? = null,

    val durationSeconds: Double? = null,

    val data: String? = null, // JSON extra data

    val synced: Boolean = false, // Whether synced to server

    val syncedAt: Long? = null
)

/**
 * Audio recording waiting for transcription.
 */
@Entity(tableName = "audio_recordings")
@Serializable
data class AudioRecording(
    @PrimaryKey(autoGenerate = true)
    val id: Long = 0,

    val timestamp: Long,

    val deviceId: String,

    val filePath: String,

    val durationSeconds: Double,

    val transcribed: Boolean = false,

    val transcription: String? = null,

    val synced: Boolean = false
)

/**
 * Export batch for Syncthing sync.
 */
@Serializable
data class ExportBatch(
    val deviceId: String,
    val exportedAt: Long,
    val events: List<ActivityEvent>
)

/**
 * Usage statistics aggregation.
 */
data class AppUsageStats(
    val packageName: String,
    val appName: String,
    val totalTimeMs: Long,
    val lastUsed: Long,
    val launchCount: Int
)
