package com.ssafy.travelmate.util.managers.preferences

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

object AuthPreferenceManager {
private lateinit var sharedPref: SharedPreferences

    fun init(context: Context) {
        //마스터키는 KeyStore에
        val masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()

        sharedPref = EncryptedSharedPreferences.create(
            context,
            "auth_prefs_encrypted", // XML 백업 예외 처리에 적은 이름
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        )
    }
    fun saveTokens(accessToken: String, refreshToken: String) {
        sharedPref.edit()
            .putString("ACCESS_TOKEN", accessToken)
            .putString("REFRESH_TOKEN", refreshToken)
            .commit()
    }
    fun saveAccessToken(token: String) {
        sharedPref.edit().putString("ACCESS_TOKEN", token).apply()
    }
    fun getAccessToken(): String? {
        return sharedPref.getString("ACCESS_TOKEN", null)
    }
    fun getRefreshToken(): String? {
        return sharedPref.getString("REFRESH_TOKEN", null)
    }
    fun saveUid(uid: String) {
        sharedPref.edit().putString("USER_UID", uid).commit()
    }
    fun getUid(): String? {
        return sharedPref.getString("USER_UID", null)
    }
    fun clearUser() {
        sharedPref.edit().clear().apply()
    }
}
