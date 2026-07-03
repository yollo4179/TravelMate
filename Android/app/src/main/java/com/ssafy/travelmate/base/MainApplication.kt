package com.ssafy.travelmate.base

import android.Manifest
import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import com.google.gson.Gson
import com.google.gson.GsonBuilder
import com.kakao.sdk.common.KakaoSdk
import com.navercorp.nid.NaverIdLoginSDK
import com.ssafy.travelmate.BuildConfig
import com.ssafy.travelmate.data.SharedPreferencesUtil
import com.ssafy.travelmate.util.managers.preferences.AuthPreferenceManager
import dagger.hilt.android.HiltAndroidApp
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit

import androidx.room.Room
import com.kakao.vectormap.KakaoMapSdk
import com.ssafy.travelmate.data.db.AppDatabase

@HiltAndroidApp
class MainApplication: Application() {


    companion object{

        const val SERVER_URL = "http://192.168.45.205:8080"
        lateinit var retrofit: Retrofit
        lateinit var sharedPreferencesUtil: SharedPreferencesUtil
        lateinit var database: AppDatabase

        //notification channel
        const val notificationChannel = "ssafy_channel"


    }
    override fun onCreate() {
        super.onCreate()
        database = Room.databaseBuilder(
            applicationContext,
            AppDatabase::class.java,
            "travelmate-db"
        ).build()

        AuthPreferenceManager.init(applicationContext)
        // Kakao SDK 초기화 (네이티브 앱 키를 넣으세요)
        KakaoSdk.init(this, BuildConfig.KAKAO_NATIVE_APP_KEY)
        KakaoMapSdk.init(this, BuildConfig.KAKAO_NATIVE_APP_KEY)
        NaverIdLoginSDK.initialize(
            this,
            BuildConfig.NAVER_CLIENT_ID,
            BuildConfig.NAVER_CLIENT_SECRET,
            "TravelMate"
        )

        // 모든 퍼미션 관련 배열
        val requiredPermissions = arrayOf(
            Manifest.permission.ACCESS_FINE_LOCATION,
            Manifest.permission.ACCESS_COARSE_LOCATION,
        )



        val okHttpClient = OkHttpClient.Builder()
            .readTimeout(5000, TimeUnit.MILLISECONDS)
            .connectTimeout(5000, TimeUnit.MILLISECONDS)
            // 로그캣에 okhttp.OkHttpClient로 검색하면 http 통신 내용을 보여줍니다.
            .addInterceptor(HttpLoggingInterceptor().setLevel(HttpLoggingInterceptor.Level.BODY))
            .addInterceptor(AuthInterceptor())
            .build()
            //GSon은 엄격한 json type을 요구하는데, 느슨하게 하기 위한 설정. success, fail이 json이 아니라 단순 문자열로 리턴될 경우 처리..
        val gson : Gson = GsonBuilder()
                .setLenient()
                .create()
            // 앱이 처음 생성되는 순간, retrofit 인스턴스를 생성
        retrofit = Retrofit.Builder()
            .baseUrl(SERVER_URL)
            .addConverterFactory(GsonConverterFactory.create(gson))
            .client(okHttpClient)
            .build()
        // notification channel 생성
        createNotificationChannel(notificationChannel, "ssafy")

    }

    private fun createNotificationChannel(id: String, name: String){
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val importance = NotificationManager.IMPORTANCE_DEFAULT
            val notificationManager: NotificationManager = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
            notificationManager.createNotificationChannel(NotificationChannel(id, name, importance))
        }
    }
}