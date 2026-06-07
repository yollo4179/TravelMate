package com.ssafy.travelmate.data

import com.ssafy.travelmate.apis.AuthApi
import com.ssafy.travelmate.base.MainApplication

class RetrofitUtil {
    companion object{
        val authService = MainApplication.retrofit.create(AuthApi::class.java)
        val userApi = MainApplication.retrofit.create(com.ssafy.travelmate.apis.UserApi::class.java)
    }
}