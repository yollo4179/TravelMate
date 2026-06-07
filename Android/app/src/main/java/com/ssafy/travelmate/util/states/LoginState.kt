package com.ssafy.travelmate.util.states

import com.ssafy.travelmate.data.remote.dto.responses.login.LoginResponse


sealed interface LoginState {

    data object Idle : LoginState

    data object Loading : LoginState

    data class Success(
        val response: LoginResponse
    ) : LoginState

    data class Error(
        val message: String
    ) : LoginState
}