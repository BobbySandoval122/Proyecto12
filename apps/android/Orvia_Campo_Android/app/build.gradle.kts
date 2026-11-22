
plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "mx.orvia.campo"
    compileSdk = 36

    defaultConfig {
        applicationId = "mx.orvia.campo"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"

        testInstrumentationRunner =
            "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        getByName("release") {
            isMinifyEnabled = false
        }
    }

    buildFeatures {
        compose = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }
}

// Compilador Kotlin moderno, compatible con JVM 17
kotlin {
    compilerOptions {
        jvmTarget.set(
            org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
        )
    }
}

dependencies {

    // Jetpack Compose BOM compatible con AGP 8.13.2 y SDK 36
    val bom = platform(
        "androidx.compose:compose-bom:2025.12.00"
    )
    implementation(bom)

    // Jetpack Compose UI
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.foundation:foundation")

    // Material Design 3
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")

    // Android Activity
    implementation("androidx.activity:activity-compose:1.11.0")

    // Android Core
    implementation("androidx.core:core-ktx:1.17.0")

    // Lifecycle
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.9.4")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.9.4")
    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:2.9.4")

    // Comunicacion REST con los microservicios de Orvia
    implementation("com.squareup.okhttp3:okhttp:4.12.0")

    // GPS y localizacion
    implementation("com.google.android.gms:play-services-location:21.3.0")

    // Escaneo de codigos QR y barras
    implementation("com.google.android.gms:play-services-code-scanner:16.1.0")

    // Pruebas unitarias
    testImplementation("junit:junit:4.13.2")

    // Herramientas de desarrollo de Compose
    debugImplementation("androidx.compose.ui:ui-tooling")
}
