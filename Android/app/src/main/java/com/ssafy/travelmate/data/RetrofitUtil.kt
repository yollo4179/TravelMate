package com.ssafy.travelmate.data

import com.ssafy.travelmate.apis.AuthApi
import com.ssafy.travelmate.apis.KakaoQueryApi
import com.ssafy.travelmate.apis.UserApi
import com.ssafy.travelmate.base.MainApplication

class RetrofitUtil {
    companion object{
        val authService = MainApplication.retrofit.create(AuthApi::class.java)
        val userApi = MainApplication.retrofit.create(UserApi::class.java)
        val kakaoQueryApi = MainApplication.retrofit.create(KakaoQueryApi::class.java)
    }
}