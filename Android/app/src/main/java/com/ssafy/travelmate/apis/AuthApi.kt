package com.ssafy.travelmate.apis

import com.ssafy.travelmate.data.remote.dto.requests.login.LoginRequest
import com.ssafy.travelmate.data.remote.dto.requests.login.OAuthSignupRequest
import com.ssafy.travelmate.data.remote.dto.responses.login.LoginResponse
import com.ssafy.travelmate.data.remote.dto.responses.login.RefreshResponse

import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.Header
import retrofit2.http.POST

interface AuthApi {

    @POST("api/auth/login/oauth")
    suspend fun Login(
        @Body request: LoginRequest //idtoken + provider
    ): Response<LoginResponse>

    @POST("api/users/signup/oauth")
    suspend fun signupOauth(
        @Header("Authorization") bearerToken: String,
        @Body request: OAuthSignupRequest
    ): Response<LoginResponse>


    //베어러 토큰 보내고 나는 리프레시 토큰 삭제 
    // ( 스프링은 레디스에 베어러(액세스) 토큰 블랙리스트 등록,  + 리프레시 삭제
    @POST("api/auth/logout")
    suspend fun logout(
        @Header("Authorization") bearerToken: String
    ): Response<String>

    // RTR 토큰 갱신: 쿠키 형식 refreshToken으로 헤더에 .
    @POST("api/auth/refresh")
    suspend fun refresh(
        @Header("Cookie") refreshTokenCookie: String //리프레시는 헤더(쿠키로 보내고 ) 액세는 바디로 받음
    ): Response<RefreshResponse>
}