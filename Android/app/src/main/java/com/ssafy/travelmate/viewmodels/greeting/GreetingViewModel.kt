package com.ssafy.travelmate.viewmodels.greeting

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ssafy.travelmate.data.db.Member
import com.ssafy.travelmate.data.remote.dto.responses.login.LoginResponse
import com.ssafy.travelmate.data.repository.MemberRepository
import com.ssafy.travelmate.repositories.AuthRepository
import com.ssafy.travelmate.util.managers.preferences.AuthPreferenceManager
import com.ssafy.travelmate.util.states.LoginState
import dagger.hilt.android.lifecycle.HiltViewModel
import android.util.Log
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

private const val TAG = "GreetingViewModel"

@HiltViewModel
class GreetingViewModel @Inject constructor(
    private val authRepository: AuthRepository,
    private val memberRepository: MemberRepository
) : ViewModel() {

    private val _loginState = MutableStateFlow<LoginState>(LoginState.Idle)
    val loginState: StateFlow<LoginState> = _loginState.asStateFlow()

    fun resetState() {
        _loginState.value = LoginState.Idle
    }

    fun login(provider: String, fetchToken: suspend () -> String?) {
        viewModelScope.launch {
            try {
                _loginState.value = LoginState.LoggingIn

                val token = fetchToken()
                    ?: throw Exception("토큰을 가져올 수 없습니다")

                val response = authRepository.login(token, provider).getOrThrow()

                if (!response.isNewUser) {
                    AuthPreferenceManager.saveTokens(response.accessToken, response.refreshToken)
                    val userInfo = authRepository.getUserProfile().getOrThrow()
                    AuthPreferenceManager.saveUid(userInfo.uid)
                    saveMember(userInfo.uid, userInfo.nickname, userInfo.email, userInfo.profileImgUrl)
                }

                _loginState.value = LoginState.LoggedIn(response)
            } catch (e: Exception) {
                Log.w(TAG, "로그인 실패: ${e.message}")
                _loginState.value = LoginState.Failed(e.message ?: "로그인에 실패했습니다")
            }
        }
    }

    fun checkAutoLogin() {
        val refreshToken = AuthPreferenceManager.getRefreshToken() ?: return
        viewModelScope.launch {
            try {
                _loginState.value = LoginState.LoggingIn

                val userInfo = authRepository.getUserProfile().getOrThrow()
                AuthPreferenceManager.saveUid(userInfo.uid)
                saveMember(userInfo.uid, userInfo.nickname, userInfo.email, userInfo.profileImgUrl)

                _loginState.value = LoginState.LoggedIn(
                    LoginResponse(
                        isNewUser = false,
                        accessToken = AuthPreferenceManager.getAccessToken() ?: "",
                        refreshToken = refreshToken,
                        tempToken = ""
                    )
                )
            } catch (e: Exception) {
                Log.w(TAG, "자동 로그인 실패: ${e.message}")
                _loginState.value = LoginState.Failed(e.message ?: "자동 로그인에 실패했습니다")
            }
        }
    }

    private suspend fun saveMember(uid: String, nickname: String, email: String?, profileImgUrl: String?) {
        val member = Member(
            uid = uid,
            name = nickname,
            email = email ?: "",
            profileImageUrl = profileImgUrl ?: ""
        )
        if (memberRepository.exists(uid)) {
            memberRepository.updateMember(member)
        } else {
            memberRepository.insertMember(member)
        }
    }
}
