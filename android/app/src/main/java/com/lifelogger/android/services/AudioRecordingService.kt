package com.lifelogger.android.services

import android.app.Notification
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.IBinder
import androidx.core.app.NotificationCompat
import com.lifelogger.android.LifeloggerApp
import com.lifelogger.android.R
import com.lifelogger.android.data.AudioRecording
import com.lifelogger.android.ui.MainActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import java.io.File
import java.io.FileOutputStream
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Service for recording audio for later transcription.
 *
 * Records audio in chunks and saves to Syncthing folder for
 * server-side transcription with Whisper.cpp.
 *
 * Note: Local on-device transcription using whisper.cpp is possible
 * but requires significant resources. Server-side is recommended.
 */
class AudioRecordingService : Service() {

    private val serviceScope = CoroutineScope(Dispatchers.IO + Job())
    private var recordingJob: Job? = null
    private var audioRecord: AudioRecord? = null
    private var isRecording = false

    private val database by lazy { (application as LifeloggerApp).database }
    private val settings by lazy { (application as LifeloggerApp).settingsRepository }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        startForeground(NOTIFICATION_ID, createNotification())
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> startRecording()
            ACTION_STOP -> stopRecording()
        }
        return START_STICKY
    }

    override fun onDestroy() {
        stopRecording()
        super.onDestroy()
    }

    private fun startRecording() {
        if (isRecording) return

        recordingJob = serviceScope.launch {
            val deviceId = settings.deviceId.first()
            val syncFolder = settings.syncFolderPath.first()

            // Create audio directory
            val audioDir = File(syncFolder, "$deviceId/audio")
            audioDir.mkdirs()

            isRecording = true

            while (isRecording) {
                try {
                    recordChunk(deviceId, audioDir)
                } catch (e: Exception) {
                    e.printStackTrace()
                }
            }
        }
    }

    private suspend fun recordChunk(deviceId: String, audioDir: File) {
        val bufferSize = AudioRecord.getMinBufferSize(
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT
        )

        audioRecord = AudioRecord(
            MediaRecorder.AudioSource.MIC,
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            bufferSize
        )

        val timestamp = SimpleDateFormat("yyyy-MM-dd_HH-mm-ss", Locale.US).format(Date())
        val filename = "audio_${timestamp}.wav"
        val file = File(audioDir, filename)

        val startTime = System.currentTimeMillis()
        val buffer = ByteArray(bufferSize)
        val audioData = mutableListOf<Byte>()

        audioRecord?.startRecording()

        // Record for CHUNK_DURATION_MS
        while (isRecording && (System.currentTimeMillis() - startTime) < CHUNK_DURATION_MS) {
            val read = audioRecord?.read(buffer, 0, bufferSize) ?: 0
            if (read > 0) {
                audioData.addAll(buffer.take(read))
            }
        }

        audioRecord?.stop()
        audioRecord?.release()
        audioRecord = null

        if (audioData.isEmpty()) return

        // Write WAV file
        writeWavFile(file, audioData.toByteArray())

        val durationSeconds = (System.currentTimeMillis() - startTime) / 1000.0

        // Save recording metadata
        database.audioRecordingDao().insert(
            AudioRecording(
                timestamp = startTime,
                deviceId = deviceId,
                filePath = file.absolutePath,
                durationSeconds = durationSeconds
            )
        )
    }

    private fun writeWavFile(file: File, audioData: ByteArray) {
        FileOutputStream(file).use { out ->
            // WAV header
            val totalDataLen = audioData.size + 36
            val byteRate = SAMPLE_RATE * 2 // 16-bit mono

            out.write("RIFF".toByteArray())
            out.write(intToByteArray(totalDataLen))
            out.write("WAVE".toByteArray())
            out.write("fmt ".toByteArray())
            out.write(intToByteArray(16)) // Sub-chunk size
            out.write(shortToByteArray(1)) // Audio format (PCM)
            out.write(shortToByteArray(1)) // Channels (mono)
            out.write(intToByteArray(SAMPLE_RATE))
            out.write(intToByteArray(byteRate))
            out.write(shortToByteArray(2)) // Block align
            out.write(shortToByteArray(16)) // Bits per sample
            out.write("data".toByteArray())
            out.write(intToByteArray(audioData.size))
            out.write(audioData)
        }
    }

    private fun intToByteArray(value: Int): ByteArray {
        return byteArrayOf(
            (value and 0xff).toByte(),
            ((value shr 8) and 0xff).toByte(),
            ((value shr 16) and 0xff).toByte(),
            ((value shr 24) and 0xff).toByte()
        )
    }

    private fun shortToByteArray(value: Int): ByteArray {
        return byteArrayOf(
            (value and 0xff).toByte(),
            ((value shr 8) and 0xff).toByte()
        )
    }

    private fun stopRecording() {
        isRecording = false
        recordingJob?.cancel()
        audioRecord?.stop()
        audioRecord?.release()
        audioRecord = null
        stopSelf()
    }

    private fun createNotification(): Notification {
        val intent = Intent(this, MainActivity::class.java)
        val pendingIntent = PendingIntent.getActivity(
            this, 0, intent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )

        return NotificationCompat.Builder(this, LifeloggerApp.CHANNEL_RECORDING)
            .setContentTitle("Lifelogger")
            .setContentText("Recording audio")
            .setSmallIcon(R.drawable.ic_notification)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .build()
    }

    companion object {
        const val ACTION_START = "com.lifelogger.android.START_RECORDING"
        const val ACTION_STOP = "com.lifelogger.android.STOP_RECORDING"
        const val NOTIFICATION_ID = 1002
        const val SAMPLE_RATE = 16000 // Whisper expects 16kHz
        const val CHUNK_DURATION_MS = 5 * 60 * 1000L // 5 minutes per chunk
    }
}
