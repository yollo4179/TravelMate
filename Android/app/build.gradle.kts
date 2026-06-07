import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    id ("com.google.devtools.ksp")
}

android {
    namespace = "com.ssafy.travelmate"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.ssafy.travelmate"
        minSdk = 24
        targetSdk = 36
        versionCode = 1
        versionName = "1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        val properties = Properties().apply {
            load(project.rootProject.file("local.properties").inputStream())
        }
        buildConfigField("String", "NAVER_CLIENT_ID", "\"${properties.getProperty("NAVER_CLIENT_ID")}\"")
        buildConfigField("String", "NAVER_CLIENT_SECRET", "\"${properties.getProperty("NAVER_CLIENT_SECRET")}\"")
        buildConfigField("String", "KAKAO_NATIVE_APP_KEY", "\"${properties.getProperty("KAKAO_NATIVE_APP_KEY")}\"")
        buildConfigField("String", "GOOGLE_CLIENT_ID", "\"${properties.getProperty("GOOGLE_CLIENT_ID")}\"")


        manifestPlaceholders["naverClientIdScheme"] = "nid${properties.getProperty("NAVER_CLIENT_ID")}"
        manifestPlaceholders["kakaoNativeAppKeyScheme"] = "kakao${properties.getProperty("KAKAO_NATIVE_APP_KEY")}"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    kotlinOptions {
        jvmTarget = "11"
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)

    implementation("androidx.appcompat:appcompat:1.6.1")
    // 네비게이션
    implementation("androidx.navigation:navigation-compose:2.8.7")


    //retrofit
    // https://github.com/square/retrofit
    implementation ("com.squareup.retrofit2:retrofit:2.9.0")
    // https://github.com/square/okhttp
    implementation ("com.squareup.okhttp3:okhttp:4.9.0")
    // https://github.com/square/retrofit/tree/master/retrofit-converters/gson
    implementation ("com.squareup.retrofit2:converter-gson:2.9.0")
    // https://github.com/square/okhttp/tree/master/okhttp-logging-interceptor
    implementation ("com.squareup.okhttp3:logging-interceptor:4.9.0")


    //Room 의존성 추가
    implementation ("androidx.room:room-runtime:2.7.0")
    annotationProcessor("androidx.room:room-compiler:2.7.0")
    implementation ("androidx.room:room-ktx:2.7.0")
//kapt --> ksp
    ksp("androidx.room:room-compiler:2.7.0")

    //Coil로 이미지 로딩.
    implementation("io.coil-kt:coil-compose:2.5.0")

    //google 계정 연동 의존성
    implementation("androidx.credentials:credentials:1.5.0")
    implementation("androidx.credentials:credentials-play-services-auth:1.5.0")
    implementation("com.google.android.libraries.identity.googleid:googleid:1.1.1")

    // Kakao SDK
    implementation("com.kakao.sdk:v2-all:2.20.1")
    implementation(libs.kakao.sdk.user)


    //네이버 SDK 의존성 추가
    implementation("com.navercorp.nid:oauth:5.9.1")

    //EncryptedSharedPreference 사용을 위한 젯펙 시큐리티 속성 추가
    implementation("androidx.security:security-crypto-ktx:1.1.0-alpha06")

    // --- 아래 테스트 및 디버그 의존성들을 추가해 주세요 ---
    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(platform(libs.androidx.compose.bom))
    androidTestImplementation(libs.androidx.compose.ui.test.junit4)

    // 프리뷰 및 레이아웃 인스펙터를 위해 필수
    debugImplementation(libs.androidx.compose.ui.tooling)
    debugImplementation(libs.androidx.compose.ui.test.manifest)


}
