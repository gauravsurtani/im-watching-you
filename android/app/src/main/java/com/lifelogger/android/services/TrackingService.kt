package com.lifelogger.android.services

import android.app.Notification
import android.app.PendingIntent
import android.app.Service
import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.IBinder
import androidx.core.app.NotificationCompat
import com.lifelogger.android.LifeloggerApp
import com.lifelogger.android.R
import com.lifelogger.android.data.ActivityEvent
import com.lifelogger.android.ui.MainActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * Foreground service that tracks app usage using UsageStatsManager.
 *
 * This is the Android equivalent of ActivityWatch - it monitors which apps
 * are being used and for how long, storing events locally for later sync.
 */
class TrackingService : Service() {

    private val serviceScope = CoroutineScope(Dispatchers.Default + Job())
    private var trackingJob: Job? = null

    private val database by lazy { (application as LifeloggerApp).database }
    private val settings by lazy { (application as LifeloggerApp).settingsRepository }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        startForeground(NOTIFICATION_ID, createNotification())
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> startTracking()
            ACTION_STOP -> stopSelf()
        }
        return START_STICKY
    }

    override fun onDestroy() {
        trackingJob?.cancel()
        super.onDestroy()
    }

    private fun startTracking() {
        trackingJob?.cancel()
        trackingJob = serviceScope.launch {
            val usageStatsManager = getSystemService(Context.USAGE_STATS_SERVICE) as UsageStatsManager

            var lastEventTime = System.currentTimeMillis()

            while (isActive) {
                val deviceId = settings.deviceId.first()
                val currentTime = System.currentTimeMillis()

                // Query usage events since last check
                val usageEvents = usageStatsManager.queryEvents(lastEventTime, currentTime)
                val events = mutableListOf<ActivityEvent>()

                var currentApp: String? = null
                var currentAppStart: Long? = null

                while (usageEvents.hasNextEvent()) {
                    val event = UsageEvents.Event()
                    usageEvents.getNextEvent(event)

                    when (event.eventType) {
                        UsageEvents.Event.ACTIVITY_RESUMED -> {
                            // App came to foreground
                            if (currentApp != null && currentAppStart != null) {
                                // Record duration of previous app
                                val duration = (event.timeStamp - currentAppStart!!) / 1000.0
                                if (duration > 1) { // Ignore very short events
                                    events.add(createEvent(
                                        deviceId = deviceId,
                                        timestamp = currentAppStart!!,
                                        packageName = currentApp!!,
                                        durationSeconds = duration
                                    ))
                                }
                            }
                            currentApp = event.packageName
                            currentAppStart = event.timeStamp
                        }
                        UsageEvents.Event.ACTIVITY_PAUSED -> {
                            // App went to background
                            if (currentApp == event.packageName && currentAppStart != null) {
                                val duration = (event.timeStamp - currentAppStart!!) / 1000.0
                                if (duration > 1) {
                                    events.add(createEvent(
                                        deviceId = deviceId,
                                        timestamp = currentAppStart!!,
                                        packageName = event.packageName,
                                        durationSeconds = duration
                                    ))
                                }
                                currentApp = null
                                currentAppStart = null
                            }
                        }
                    }
                }

                // Save events to database
                if (events.isNotEmpty()) {
                    database.activityEventDao().insertAll(events)
                }

                lastEventTime = currentTime
                delay(POLL_INTERVAL_MS)
            }
        }
    }

    private fun createEvent(
        deviceId: String,
        timestamp: Long,
        packageName: String,
        durationSeconds: Double
    ): ActivityEvent {
        val appName = try {
            val appInfo = packageManager.getApplicationInfo(packageName, 0)
            packageManager.getApplicationLabel(appInfo).toString()
        } catch (e: PackageManager.NameNotFoundException) {
            packageName
        }

        return ActivityEvent(
            timestamp = timestamp,
            deviceId = deviceId,
            source = "android_usage",
            appName = appName,
            packageName = packageName,
            durationSeconds = durationSeconds
        )
    }

    private fun createNotification(): Notification {
        val intent = Intent(this, MainActivity::class.java)
        val pendingIntent = PendingIntent.getActivity(
            this, 0, intent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )

        return NotificationCompat.Builder(this, LifeloggerApp.CHANNEL_TRACKING)
            .setContentTitle("Lifelogger")
            .setContentText("Tracking activity")
            .setSmallIcon(R.drawable.ic_notification)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .build()
    }

    companion object {
        const val ACTION_START = "com.lifelogger.android.START_TRACKING"
        const val ACTION_STOP = "com.lifelogger.android.STOP_TRACKING"
        const val NOTIFICATION_ID = 1001
        const val POLL_INTERVAL_MS = 30_000L // 30 seconds
    }
}
