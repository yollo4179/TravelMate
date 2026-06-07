package com.ssafy.travelmate.util.managers

import android.content.Context
import android.util.Log
import androidx.credentials.CredentialManager
import androidx.credentials.CustomCredential
import androidx.credentials.GetCredentialRequest
import androidx.credentials.GetCredentialResponse
import androidx.credentials.exceptions.GetCredentialException
import com.google.android.libraries.identity.googleid.GetGoogleIdOption
import com.google.android.libraries.identity.googleid.GoogleIdTokenCredential
import com.ssafy.travelmate.BuildConfig

class GoogleAuthManager {

    companion object {
        private const val TAG = "GoogleAuthManager"
        private const val CLIENT_ID  = BuildConfig.GOOGLE_CLIENT_ID;

            //"657162403421-7a5iko91v3liq0ephqnpdtl88ajugar8.apps.googleusercontent.com"
    }

    suspend fun getIdToken(context: Context): String? {
        return try {
            val credentialManager = CredentialManager.create(context)

            val googleIdOption = GetGoogleIdOption.Builder()
                .setServerClientId(CLIENT_ID)
                .setFilterByAuthorizedAccounts(false)
                .setAutoSelectEnabled(false) // 테스트를 위해 자동 선택 해제
                .build()

            val request = GetCredentialRequest.Builder()
                .addCredentialOption(googleIdOption)
                .build()

            val result = credentialManager.getCredential(
                context = context,
                request = request
            )

            val token = handleSignIn(result)
            if (token == null) {
                Log.w(TAG, "인증은 성공했으나 ID 토큰을 추출하지 못했습니다.")
            }
            token
        } catch (e: GetCredentialException) {
            // 사용자가 취소했거나, 설정 오류인 경우 여기서 잡힘
            Log.e(TAG, "Credential Manager 에러 [${e.type}]: ${e.message}")
            null
        } catch (e: Exception) {
            Log.e(TAG, "예상치 못한 인증 에러", e)
            null
        }
    }

    private fun handleSignIn(result: GetCredentialResponse): String? {
        val credential = result.credential
        Log.d(TAG, "받은 인증 타입: ${credential.type}")

        if (credential is CustomCredential &&
            credential.type == GoogleIdTokenCredential.TYPE_GOOGLE_ID_TOKEN_CREDENTIAL
        ) {
            return try {
                val googleCredential = GoogleIdTokenCredential.createFrom(credential.data)
                googleCredential.idToken
            } catch (e: Exception) {
                Log.e(TAG, "GoogleIdTokenCredential 파싱 실패", e)
                null
            }
        }
        return null
    }
}