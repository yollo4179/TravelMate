package com.ssafy.travelmate.apis

import com.ssafy.travelmate.data.remote.dto.responses.login.UserInfoResponse
import retrofit2.Response
import retrofit2.http.GET

interface UserApi {
    @GET("api/users/me")
    suspend fun getUserProfile(): Response<UserInfoResponse>
}
