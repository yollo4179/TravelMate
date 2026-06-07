package com.ssafy.travelmate.repositories

import android.widget.Toast
import com.ssafy.travelmate.apis.AuthApi
import com.ssafy.travelmate.data.RetrofitUtil
import com.ssafy.travelmate.data.remote.dto.requests.login.LoginRequest
import com.ssafy.travelmate.data.remote.dto.requests.login.OAuthSignupRequest

import com.ssafy.travelmate.data.remote.dto.responses.login.LoginResponse

class AuthRepository() {

    suspend fun login(
        idToken: String,
        provider: String
    ): Result<LoginResponse> {

        return try {

            val response =
                RetrofitUtil.authService.Login(
                    LoginRequest(idToken,provider )
                )

            if (response.isSuccessful &&
                response.body() != null
            ) {

                Result.success(
                    response.body()!!
                )

            } else {

                Result.failure(
                    Exception(
                        "Login Failed : ${response.code()}"
                    )
                )
            }

        } catch (e: Exception) {

            Result.failure(e)
        }
    }

    suspend fun signupOauth(
        tempToken: String,
        nickname: String
    ): Result<LoginResponse> {
        return try {
            val response = RetrofitUtil.authService.signupOauth(
                "Bearer $tempToken",
                OAuthSignupRequest(nickname)
            )

            if (response.isSuccessful && response.body() != null) {
                Result.success(response.body()!!)
            } else {

                Result.failure(Exception("Signup Failed : ${response.code()}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun getUserProfile(): Result<com.ssafy.travelmate.data.remote.dto.responses.login.UserInfoResponse> {
        return try {
            val response = RetrofitUtil.userApi.getUserProfile()
            if (response.isSuccessful && response.body() != null) {
                Result.success(response.body()!!)
            } else {
                Result.failure(Exception("Get Profile Failed : ${response.code()}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
}