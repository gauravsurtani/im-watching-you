# Proguard rules for Lifelogger

# Keep Kotlin serialization
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.AnnotationsKt

-keepclassmembers class kotlinx.serialization.json.** {
    *** Companion;
}
-keepclasseswithmembers class kotlinx.serialization.json.** {
    kotlinx.serialization.KSerializer serializer(...);
}

-keep,includedescriptorclasses class com.lifelogger.android.**$$serializer { *; }
-keepclassmembers class com.lifelogger.android.** {
    *** Companion;
}
-keepclasseswithmembers class com.lifelogger.android.** {
    kotlinx.serialization.KSerializer serializer(...);
}

# Keep Room entities
-keep class com.lifelogger.android.data.** { *; }

# OkHttp
-dontwarn okhttp3.**
-dontwarn okio.**
-keep class okhttp3.** { *; }
