package com.lifelogger.android.data

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface ActivityEventDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(event: ActivityEvent): Long

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(events: List<ActivityEvent>)

    @Query("SELECT * FROM activity_events WHERE synced = 0 ORDER BY timestamp ASC")
    suspend fun getUnsynced(): List<ActivityEvent>

    @Query("SELECT * FROM activity_events WHERE synced = 0 ORDER BY timestamp ASC LIMIT :limit")
    suspend fun getUnsyncedBatch(limit: Int): List<ActivityEvent>

    @Query("UPDATE activity_events SET synced = 1, syncedAt = :syncedAt WHERE id IN (:ids)")
    suspend fun markSynced(ids: List<Long>, syncedAt: Long)

    @Query("SELECT * FROM activity_events WHERE timestamp >= :since ORDER BY timestamp DESC")
    fun getEventsSince(since: Long): Flow<List<ActivityEvent>>

    @Query("SELECT * FROM activity_events WHERE timestamp BETWEEN :start AND :end ORDER BY timestamp DESC")
    suspend fun getEventsInRange(start: Long, end: Long): List<ActivityEvent>

    @Query("SELECT COUNT(*) FROM activity_events WHERE synced = 0")
    fun getUnsyncedCount(): Flow<Int>

    @Query("SELECT COUNT(*) FROM activity_events")
    fun getTotalCount(): Flow<Int>

    @Query("""
        SELECT appName, packageName, SUM(durationSeconds) as totalSeconds, COUNT(*) as eventCount
        FROM activity_events
        WHERE timestamp >= :since AND appName IS NOT NULL
        GROUP BY packageName
        ORDER BY totalSeconds DESC
        LIMIT :limit
    """)
    suspend fun getTopApps(since: Long, limit: Int): List<AppUsageSummary>

    @Query("DELETE FROM activity_events WHERE synced = 1 AND timestamp < :before")
    suspend fun deleteSyncedBefore(before: Long): Int
}

data class AppUsageSummary(
    val appName: String?,
    val packageName: String?,
    val totalSeconds: Double,
    val eventCount: Int
)

@Dao
interface AudioRecordingDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(recording: AudioRecording): Long

    @Query("SELECT * FROM audio_recordings WHERE transcribed = 0 ORDER BY timestamp ASC")
    suspend fun getUntranscribed(): List<AudioRecording>

    @Query("SELECT * FROM audio_recordings WHERE synced = 0 ORDER BY timestamp ASC")
    suspend fun getUnsynced(): List<AudioRecording>

    @Query("UPDATE audio_recordings SET transcribed = 1, transcription = :transcription WHERE id = :id")
    suspend fun setTranscription(id: Long, transcription: String)

    @Query("UPDATE audio_recordings SET synced = 1 WHERE id IN (:ids)")
    suspend fun markSynced(ids: List<Long>)

    @Query("DELETE FROM audio_recordings WHERE synced = 1 AND timestamp < :before")
    suspend fun deleteSyncedBefore(before: Long): Int
}
