package com.ssafy.travelmate.util.managers

import android.content.Context
import android.util.Log
import com.kakao.sdk.auth.model.OAuthToken
import com.kakao.sdk.common.util.Utility
import com.kakao.sdk.user.UserApiClient
import kotlin.coroutines.resume
import kotlin.coroutines.suspendCoroutine

class KakaoAuthManager {
    companion object {
        private const val TAG = "KakaoAuthManager"
    }

    suspend fun login(context: Context): String? = suspendCoroutine { continuation ->


        // 카카오톡 설치 여부 확인
        if (UserApiClient.instance.isKakaoTalkLoginAvailable(context)) {
            // 카카오톡으로 로그인
            UserApiClient.instance.loginWithKakaoTalk(context) { token, error ->
                handleResult(token, error, continuation)
            }
        } else {
            // 카카오 계정(웹 브라우저)으로 로그인
            UserApiClient.instance.loginWithKakaoAccount(context) { token, error ->
                handleResult(token, error, continuation)
            }
        }

    }

    private fun handleResult(
        token: OAuthToken?,
        error: Throwable?,
        continuation: kotlin.coroutines.Continuation<String?>
    ) {
        if (error != null) {
            Log.e(TAG, "카카오 로그인 실패", error)
            continuation.resume(null)
        } else if (token != null) {
            val idToken = token.idToken
            Log.d(TAG, "카카오 로그인 성공 (idToken): $idToken")
            continuation.resume(idToken)
        }
    }
}
