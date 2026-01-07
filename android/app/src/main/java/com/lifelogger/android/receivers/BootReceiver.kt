package com.lifelogger.android.receivers

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.lifelogger.android.services.SyncWorker
import com.lifelogger.android.services.TrackingService

/**
 * Receiver that restarts tracking services after device reboot.
 */
class BootReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED ||
            intent.action == "android.intent.action.QUICKBOOT_POWERON") {

            // Restart tracking service
            val trackingIntent = Intent(context, TrackingService::class.java).apply {
                action = TrackingService.ACTION_START
            }
            context.startForegroundService(trackingIntent)

            // Reschedule sync worker
            SyncWorker.schedule(context)
        }
    }
}
