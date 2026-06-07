package com.ssafy.travelmate.base

import android.util.Log
import com.google.gson.Gson
import com.ssafy.travelmate.data.remote.dto.responses.login.RefreshResponse
import com.ssafy.travelmate.util.events.GlobalEventBus
import com.ssafy.travelmate.util.managers.preferences.AuthPreferenceManager
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import org.json.JSONObject
import java.io.IOException

class AuthInterceptor : Interceptor {

    @Throws(IOException::class)
    override fun intercept(chain: Interceptor.Chain): Response {
        /*******************************요청 전 *****************/

        //1. 현재 보내려는 요청
        val originalRequest = chain.request()

        //2. 프리퍼런스 확인
        val accessToken = AuthPreferenceManager.getAccessToken()
        val requestBuilder = originalRequest.newBuilder() //요청을 내가 커스터마이징
        
        //헤더에 삽입(스프링 요구사항)- 요청 보내기 전에 헤더에 액세스 실어라
        if (accessToken != null && originalRequest.header("Authorization") == null) {
            requestBuilder.addHeader("Authorization", "Bearer $accessToken")
        }




        /**********************************요청결과를 받았다***************************************/

        var response = chain.proceed(requestBuilder.build())

        // 401 Unauthorized 에러 감지
        // (스프링에서는 에러코드를 401로만 줘야하고 예외를 Enum - ErrorCode로만 던져야함 -파싱 조건)
        if (response.code == 401) {
            val responseBodyString = response.peekBody(Long.MAX_VALUE).string()
            var errorCode = ""
            try {
                val json = JSONObject(responseBodyString)
                errorCode = json.getString("code")
            } catch (e: Exception) {
                // 파싱 실패
            }

            when (errorCode) {
                "ERR_ACCESS_TOKEN_EXPIRED" -> {
                    // 리프레시 시도
                    val refreshToken = AuthPreferenceManager.getRefreshToken()
                    if (refreshToken != null) {
                        val refreshRequest = Request.Builder()
                            .url("${MainApplication.SERVER_URL}api/auth/refresh")
                            .post("".toRequestBody("application/json".toMediaTypeOrNull()))
                            .addHeader("Cookie", "refreshToken=$refreshToken")
                            .build()

                        val refreshResponse = chain.proceed(refreshRequest)
                        if (refreshResponse.isSuccessful) {
                            // RTR 성공 새 토큰 파싱
                            val refreshBodyString = refreshResponse.peekBody(Long.MAX_VALUE).string()
                            try {
                                val refreshData = Gson().fromJson(refreshBodyString, RefreshResponse::class.java)
                                val newAccessToken = refreshData.accessToken
                                
                                // 쿠키에서 새 리프레시 토큰 추출
                                var newRefreshToken = refreshToken!!
                                for (header in refreshResponse.headers("Set-Cookie")) {
                                    if (header.contains("refreshToken=")) {
                                        newRefreshToken = header.substringAfter("refreshToken=").substringBefore(";")
                                    }
                                }


                                AuthPreferenceManager.saveTokens(newAccessToken, newRefreshToken)

                                // 기존 원래 하려던 요청 다시 보내기
                                response.close() // 기존 실패한 응답 닫기
                                val newRequestBuilder = originalRequest.newBuilder()
                                    .header("Authorization", "Bearer $newAccessToken")
                                return chain.proceed(newRequestBuilder.build())

                            } catch (e: Exception) {
                                Log.e("AuthInterceptor", "리프레시 토큰 파싱 실패", e)
                                emitExpiredAndClear(errorCode)
                            }
                        } else {
                            // 리프레시 자체가 실패 (만료 등)
                            emitExpiredAndClear("ERR_REFRESH_TOKEN_EXPIRED")
                        }
                    } else {
                        emitExpiredAndClear("ERR_REFRESH_TOKEN_EXPIRED")
                    }
                }

                "ERR_REFRESH_TOKEN_EXPIRED", "ERR_TEMP_TOKEN_EXPIRED" -> {
                    emitExpiredAndClear(errorCode) //리프레시나 임시 만료면 걍 팅겨버려라( 오래 접속 안하면 팅길 것
                }
                else -> {
                    // 기타 401 에러( 내가 다른거를 정의해서 확장 가능)
                    emitExpiredAndClear("ERR_UNKNOWN_401")
                }
            }
        }

        return response
    }

    private fun emitExpiredAndClear(errorCode: String) {
        AuthPreferenceManager.clearUser()
        GlobalEventBus.emitSessionExpired(errorCode)
    }
}
