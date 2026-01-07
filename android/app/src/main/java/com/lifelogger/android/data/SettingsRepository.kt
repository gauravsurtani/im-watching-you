package com.lifelogger.android.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.longPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import java.util.UUID

private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "settings")

/**
 * Repository for app settings stored in DataStore.
 */
class SettingsRepository(private val context: Context) {

    private object Keys {
        val DEVICE_ID = stringPreferencesKey("device_id")
        val TRACKING_ENABLED = booleanPreferencesKey("tracking_enabled")
        val AUDIO_RECORDING_ENABLED = booleanPreferencesKey("audio_recording_enabled")
        val SYNC_FOLDER_PATH = stringPreferencesKey("sync_folder_path")
        val SYNC_INTERVAL_MINUTES = intPreferencesKey("sync_interval_minutes")
        val LAST_SYNC_TIME = longPreferencesKey("last_sync_time")
        val RETENTION_DAYS = intPreferencesKey("retention_days")
        val OLLAMA_URL = stringPreferencesKey("ollama_url")
    }

    val deviceId: Flow<String> = context.dataStore.data.map { prefs ->
        prefs[Keys.DEVICE_ID] ?: generateDeviceId()
    }

    val trackingEnabled: Flow<Boolean> = context.dataStore.data.map { prefs ->
        prefs[Keys.TRACKING_ENABLED] ?: true
    }

    val audioRecordingEnabled: Flow<Boolean> = context.dataStore.data.map { prefs ->
        prefs[Keys.AUDIO_RECORDING_ENABLED] ?: false
    }

    val syncFolderPath: Flow<String> = context.dataStore.data.map { prefs ->
        prefs[Keys.SYNC_FOLDER_PATH] ?: "/storage/emulated/0/Syncthing/lifelogger"
    }

    val syncIntervalMinutes: Flow<Int> = context.dataStore.data.map { prefs ->
        prefs[Keys.SYNC_INTERVAL_MINUTES] ?: 15
    }

    val lastSyncTime: Flow<Long> = context.dataStore.data.map { prefs ->
        prefs[Keys.LAST_SYNC_TIME] ?: 0L
    }

    val retentionDays: Flow<Int> = context.dataStore.data.map { prefs ->
        prefs[Keys.RETENTION_DAYS] ?: 30
    }

    val ollamaUrl: Flow<String> = context.dataStore.data.map { prefs ->
        prefs[Keys.OLLAMA_URL] ?: "http://localhost:11434"
    }

    suspend fun setDeviceId(id: String) {
        context.dataStore.edit { prefs ->
            prefs[Keys.DEVICE_ID] = id
        }
    }

    suspend fun setTrackingEnabled(enabled: Boolean) {
        context.dataStore.edit { prefs ->
            prefs[Keys.TRACKING_ENABLED] = enabled
        }
    }

    suspend fun setAudioRecordingEnabled(enabled: Boolean) {
        context.dataStore.edit { prefs ->
            prefs[Keys.AUDIO_RECORDING_ENABLED] = enabled
        }
    }

    suspend fun setSyncFolderPath(path: String) {
        context.dataStore.edit { prefs ->
            prefs[Keys.SYNC_FOLDER_PATH] = path
        }
    }

    suspend fun setSyncIntervalMinutes(minutes: Int) {
        context.dataStore.edit { prefs ->
            prefs[Keys.SYNC_INTERVAL_MINUTES] = minutes
        }
    }

    suspend fun setLastSyncTime(time: Long) {
        context.dataStore.edit { prefs ->
            prefs[Keys.LAST_SYNC_TIME] = time
        }
    }

    suspend fun setRetentionDays(days: Int) {
        context.dataStore.edit { prefs ->
            prefs[Keys.RETENTION_DAYS] = days
        }
    }

    suspend fun setOllamaUrl(url: String) {
        context.dataStore.edit { prefs ->
            prefs[Keys.OLLAMA_URL] = url
        }
    }

    private suspend fun generateDeviceId(): String {
        val id = "android-${UUID.randomUUID().toString().take(8)}"
        setDeviceId(id)
        return id
    }
}
