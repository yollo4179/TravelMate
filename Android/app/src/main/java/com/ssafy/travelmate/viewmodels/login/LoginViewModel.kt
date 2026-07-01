package com.ssafy.travelmate.viewmodels.login

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ssafy.travelmate.data.remote.dto.responses.login.LoginResponse
import com.ssafy.travelmate.repositories.AuthRepository
import com.ssafy.travelmate.util.managers.preferences.AuthPreferenceManager
import com.ssafy.travelmate.util.states.LoginState
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

import com.ssafy.travelmate.data.db.Member
import com.ssafy.travelmate.data.repository.MemberRepository


@HiltViewModel
class LoginViewModel @Inject constructor(
    private val repository: AuthRepository,
    private val memberRepository: MemberRepository
) : ViewModel() {

    private val _loginState = MutableStateFlow<LoginState>(LoginState.Idle)
    val loginState = _loginState.asStateFlow()

    fun resetState(){
        _loginState.value = LoginState.Idle
    }

    private suspend fun fetchAndSaveUserProfile() {
        repository.getUserProfile().onSuccess { userInfo ->
            AuthPreferenceManager.saveUid(userInfo.uid)
            val member = Member(
                uid = userInfo.uid,
                name = userInfo.nickname,
                email = userInfo.email ?: "",
                profileImageUrl = userInfo.profileImgUrl ?: ""
            )
            if (memberRepository.exists(userInfo.uid)) {
                memberRepository.updateMember(member)
            } else {
                memberRepository.insertMember(member)
            }
        }.onFailure {
            // 프로필 조회 실패 시 예외 처리 (필요에 따라)
        }
    }

    fun login(idToken: String, provider: String) {
        viewModelScope.launch {
            _loginState.value = LoginState.LoggingIn
            repository.login(idToken, provider)
                .onSuccess {
                    if (!it.isNewUser) {
                        AuthPreferenceManager.saveTokens(it.accessToken, it.refreshToken)
                        fetchAndSaveUserProfile()
                    }
                    _loginState.value = LoginState.LoggedIn(it)
                }
                .onFailure {
                    _loginState.value = LoginState.Failed(it.message ?: "Unknown Error")
                }
        }
    }

    fun signupOauth(nickname: String, tempToken: String) {
        viewModelScope.launch {
            _loginState.value = LoginState.LoggingIn
            repository.signupOauth(tempToken, nickname)
                .onSuccess {
                    AuthPreferenceManager.saveTokens(it.accessToken, it.refreshToken)
                    fetchAndSaveUserProfile()
                    _loginState.value = LoginState.LoggedIn(it)
                }
                .onFailure {
                    _loginState.value = LoginState.Failed(it.message ?: "Signup Failed")
                }
        }
    }

    fun checkAutoLogin() {
        val refreshToken = AuthPreferenceManager.getRefreshToken()
        if (refreshToken != null) {
            viewModelScope.launch {
                _loginState.value = LoginState.LoggingIn
                repository.getUserProfile()
                    .onSuccess { userInfo ->
                        AuthPreferenceManager.saveUid(userInfo.uid)
                        val member = Member(
                            uid = userInfo.uid,
                            name = userInfo.nickname,
                            email = userInfo.email ?: "",
                            profileImageUrl = userInfo.profileImgUrl ?: ""
                        )
                        if (memberRepository.exists(userInfo.uid)) {
                            memberRepository.updateMember(member)
                        } else {
                            memberRepository.insertMember(member)
                        }

                        val loginResponse = LoginResponse(
                            isNewUser = false,
                            accessToken = AuthPreferenceManager.getAccessToken() ?: "",
                            refreshToken = refreshToken,
                            tempToken = ""
                        )
                        _loginState.value = LoginState.LoggedIn(loginResponse)
                    }
                    .onFailure {
                        _loginState.value = LoginState.Failed(it.message ?: "Auto Login Failed")
                    }
            }
        }
    }
}
