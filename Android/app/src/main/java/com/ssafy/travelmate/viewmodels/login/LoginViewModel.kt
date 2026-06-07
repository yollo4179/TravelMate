package com.ssafy.travelmate.viewmodels.login

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ssafy.travelmate.data.remote.dto.responses.login.LoginResponse
import com.ssafy.travelmate.repositories.AuthRepository
import com.ssafy.travelmate.util.managers.preferences.AuthPreferenceManager
import com.ssafy.travelmate.util.states.LoginState
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

class LoginViewModel(
    private val repository: AuthRepository // MainActivity에서 주입 받습니다.
) : ViewModel() {

    private val _loginState =
        MutableStateFlow<LoginState>(
            LoginState.Idle
        )

    val loginState =
        _loginState.asStateFlow()


    fun resetState(){
        _loginState.value = LoginState.Idle
    }
    fun login(
        idToken: String,
        provider: String
    ) {

        viewModelScope.launch  {

            _loginState.value = LoginState.Loading
            repository
                .login(idToken,provider)
                .onSuccess {
                    _loginState.value =
                        LoginState.Success(it)
                }
                .onFailure {
                    _loginState.value =
                        LoginState.Error(
                            it.message ?: "Unknown Error"
                        )
                }
        }
    }

    fun signupOauth(nickname: String, tempToken: String) {
        viewModelScope.launch {
            _loginState.value = LoginState.Loading
            repository.signupOauth(tempToken, nickname)
                .onSuccess {
                    _loginState.value = LoginState.Success(it)
                }
                .onFailure {
                    _loginState.value = LoginState.Error(it.message ?: "Signup Failed")
                }
        }
    }

    fun checkAutoLogin() {
        val refreshToken = com.ssafy.travelmate.util.managers.preferences.AuthPreferenceManager.getRefreshToken()
        if (refreshToken != null) {
            viewModelScope.launch {
                _loginState.value = LoginState.Loading //스피너 같은 화면 띄운다.
                repository.getUserProfile()
                    .onSuccess {
                        val loginResponse = LoginResponse(
                            isNewUser = false,
                            accessToken = AuthPreferenceManager.getAccessToken() ?: "", //사실 리프레시 호출 확정임
                            refreshToken = refreshToken,
                            tempToken = ""
                        )
                        _loginState.value = LoginState.Success(loginResponse)
                    }
                    .onFailure {
                        _loginState.value = LoginState.Error(it.message ?: "Auto Login Failed")
                    }
            }
        }
    }
}
