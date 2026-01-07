package com.lifelogger.android.services

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.lifelogger.android.LifeloggerApp
import com.lifelogger.android.data.ExportBatch
import kotlinx.coroutines.flow.first
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.TimeUnit

/**
 * Worker that exports activity events to JSON files in the Syncthing folder.
 *
 * This uses the same export format as the desktop ActivityWatch export script,
 * allowing the server to ingest data from both sources consistently.
 */
class SyncWorker(
    context: Context,
    params: WorkerParameters
) : CoroutineWorker(context, params) {

    private val app = applicationContext as LifeloggerApp
    private val database = app.database
    private val settings = app.settingsRepository

    private val json = Json {
        prettyPrint = true
        ignoreUnknownKeys = true
    }

    override suspend fun doWork(): Result {
        return try {
            val deviceId = settings.deviceId.first()
            val syncFolder = settings.syncFolderPath.first()

            // Create sync folder if needed
            val baseDir = File(syncFolder, deviceId)
            val activityDir = File(baseDir, "activity")
            activityDir.mkdirs()

            // Get unsynced events
            val events = database.activityEventDao().getUnsyncedBatch(BATCH_SIZE)

            if (events.isEmpty()) {
                return Result.success()
            }

            // Create export batch
            val batch = ExportBatch(
                deviceId = deviceId,
                exportedAt = System.currentTimeMillis(),
                events = events
            )

            // Write to file
            val timestamp = SimpleDateFormat("yyyy-MM-dd_HH-mm-ss", Locale.US).format(Date())
            val filename = "activity_${timestamp}.json"
            val file = File(activityDir, filename)

            file.writeText(json.encodeToString(batch))

            // Mark events as synced
            val eventIds = events.map { it.id }
            database.activityEventDao().markSynced(eventIds, System.currentTimeMillis())

            // Update last sync time
            settings.setLastSyncTime(System.currentTimeMillis())

            // Clean up old synced events
            val retentionDays = settings.retentionDays.first()
            val cutoff = System.currentTimeMillis() - (retentionDays * 24 * 60 * 60 * 1000L)
            database.activityEventDao().deleteSyncedBefore(cutoff)

            Result.success()
        } catch (e: Exception) {
            if (runAttemptCount < 3) {
                Result.retry()
            } else {
                Result.failure()
            }
        }
    }

    companion object {
        const val WORK_NAME = "sync_work"
        const val BATCH_SIZE = 500

        fun schedule(context: Context, intervalMinutes: Int = 15) {
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(NetworkType.NOT_REQUIRED) // Local sync via Syncthing
                .setRequiresBatteryNotLow(true)
                .build()

            val request = PeriodicWorkRequestBuilder<SyncWorker>(
                intervalMinutes.toLong(), TimeUnit.MINUTES
            )
                .setConstraints(constraints)
                .build()

            WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                WORK_NAME,
                ExistingPeriodicWorkPolicy.UPDATE,
                request
            )
        }

        fun cancel(context: Context) {
            WorkManager.getInstance(context).cancelUniqueWork(WORK_NAME)
        }

        fun runNow(context: Context) {
            val request = androidx.work.OneTimeWorkRequestBuilder<SyncWorker>().build()
            WorkManager.getInstance(context).enqueue(request)
        }
    }
}
