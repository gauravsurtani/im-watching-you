package com.lifelogger.android

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import com.lifelogger.android.data.AppDatabase
import com.lifelogger.android.data.SettingsRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob

/**
 * Main application class for Lifelogger Android client.
 *
 * Handles initialization of:
 * - Local database for activity storage
 * - Background tracking services
 * - Syncthing integration for server sync
 */
class LifeloggerApp : Application() {

    // Application scope for background operations
    val applicationScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    // Lazy initialization of database
    val database: AppDatabase by lazy {
        AppDatabase.getDatabase(this)
    }

    // Settings repository
    val settingsRepository: SettingsRepository by lazy {
        SettingsRepository(this)
    }

    override fun onCreate() {
        super.onCreate()
        instance = this
        createNotificationChannels()
    }

    private fun createNotificationChannels() {
        val notificationManager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

        // Tracking service channel
        val trackingChannel = NotificationChannel(
            CHANNEL_TRACKING,
            "Activity Tracking",
            NotificationManager.IMPORTANCE_LOW
        ).apply {
            description = "Shows when activity tracking is active"
            setShowBadge(false)
        }

        // Recording service channel
        val recordingChannel = NotificationChannel(
            CHANNEL_RECORDING,
            "Audio Recording",
            NotificationManager.IMPORTANCE_DEFAULT
        ).apply {
            description = "Shows when audio recording is active"
        }

        // Sync status channel
        val syncChannel = NotificationChannel(
            CHANNEL_SYNC,
            "Sync Status",
            NotificationManager.IMPORTANCE_LOW
        ).apply {
            description = "Shows sync progress with server"
            setShowBadge(false)
        }

        // Alerts channel
        val alertsChannel = NotificationChannel(
            CHANNEL_ALERTS,
            "Alerts & Digests",
            NotificationManager.IMPORTANCE_DEFAULT
        ).apply {
            description = "Daily digests and important alerts"
        }

        notificationManager.createNotificationChannels(
            listOf(trackingChannel, recordingChannel, syncChannel, alertsChannel)
        )
    }

    companion object {
        const val CHANNEL_TRACKING = "tracking_service"
        const val CHANNEL_RECORDING = "recording_service"
        const val CHANNEL_SYNC = "sync_status"
        const val CHANNEL_ALERTS = "alerts"

        lateinit var instance: LifeloggerApp
            private set
    }
}
