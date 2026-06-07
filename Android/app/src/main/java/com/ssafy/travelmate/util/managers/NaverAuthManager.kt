package com.ssafy.travelmate.util.managers

import android.content.Context
import android.util.Log
import com.navercorp.nid.NaverIdLoginSDK
import com.navercorp.nid.oauth.OAuthLoginCallback
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume

class NaverAuthManager {
    private val TAG = "NaverAuthManager"

    suspend fun login(context: Context): String? = suspendCancellableCoroutine { continuation ->
        val oauthLoginCallback = object : OAuthLoginCallback {
            override fun onSuccess() {
                val token = NaverIdLoginSDK.getAccessToken()
                Log.d(TAG, "네이버 로그인 성공:${token}")
                continuation.resume(token)
            }

            override fun onFailure(httpStatus: Int, message: String) {
                val errorCode = NaverIdLoginSDK.getLastErrorCode().code
                val errorDescription = NaverIdLoginSDK.getLastErrorDescription()
                Log.e(TAG, "네이버 로그인 실패: $errorCode, $errorDescription")
                continuation.resume(null)
            }

            override fun onError(errorCode: Int, message: String) {
                onFailure(errorCode, message)
            }
        }

        NaverIdLoginSDK.authenticate(context, oauthLoginCallback)
    }

    suspend fun disconnect(context: Context): Boolean = suspendCancellableCoroutine { continuation ->
        val callback = object : OAuthLoginCallback {
            override fun onSuccess() {
                Log.d(TAG, "연동 해제 성공")
                continuation.resume(true)
            }
            override fun onFailure(httpStatus: Int, message: String) {
                Log.e(TAG, "연동 해제 실패: $message")
                continuation.resume(false)
            }
            override fun onError(errorCode: Int, message: String) {
                onFailure(errorCode, message)
            }
        }

        // NidOAuthLogin을 직접 생성해서 호출하는 방식이 가장 정확합니다.
        com.navercorp.nid.oauth.NidOAuthLogin().callDeleteTokenApi( callback)
    }


}