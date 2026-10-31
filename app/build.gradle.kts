plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

android {
    namespace = "app.funkerlitelab"
    compileSdk = 34

    defaultConfig {
        applicationId = "app.funkerlitelab"
        minSdk = 24
        targetSdk = 34
        versionCode = 3
        versionName = "0.5.3"
        ndk { abiFilters += listOf("arm64-v8a", "armeabi-v7a") }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

chaquopy {
    defaultConfig {
        version = "3.11"
        pip { install("Pillow") }
    }
}
