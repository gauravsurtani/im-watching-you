package com.lifelogger.android.data

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase

/**
 * Room database for local activity storage.
 *
 * Events are stored locally and periodically exported to JSON files
 * in the Syncthing folder for sync to the server.
 */
@Database(
    entities = [ActivityEvent::class, AudioRecording::class],
    version = 1,
    exportSchema = true
)
abstract class AppDatabase : RoomDatabase() {

    abstract fun activityEventDao(): ActivityEventDao
    abstract fun audioRecordingDao(): AudioRecordingDao

    companion object {
        @Volatile
        private var INSTANCE: AppDatabase? = null

        fun getDatabase(context: Context): AppDatabase {
            return INSTANCE ?: synchronized(this) {
                val instance = Room.databaseBuilder(
                    context.applicationContext,
                    AppDatabase::class.java,
                    "lifelogger_db"
                )
                    .fallbackToDestructiveMigration()
                    .build()
                INSTANCE = instance
                instance
            }
        }
    }
}
