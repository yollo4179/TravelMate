package com.ssafy.travelmate.util.states

import com.ssafy.travelmate.data.remote.dto.responses.login.LoginResponse


sealed interface LoginState {

    data object Idle : LoginState

    data object LoggingIn : LoginState

    data class LoggedIn(
        val response: LoginResponse
    ) : LoginState

    data class Failed(
        val message: String
    ) : LoginState
}
