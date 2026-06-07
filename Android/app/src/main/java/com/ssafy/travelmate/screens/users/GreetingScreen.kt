package com.ssafy.travelmate.screens.users

import android.R
import android.util.Log
import androidx.compose.foundation.layout.*
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.navercorp.nid.NaverIdLoginSDK
import com.ssafy.travelmate.BuildConfig
import com.ssafy.travelmate.components.GoogleLoginButton
import com.ssafy.travelmate.components.KakaoLoginButton
import com.ssafy.travelmate.components.NaverLoginButton
import com.ssafy.travelmate.ui.theme.KakaoLabel
import com.ssafy.travelmate.ui.theme.KakaoYellow
import com.ssafy.travelmate.ui.theme.NaverGreen
import com.ssafy.travelmate.util.managers.GoogleAuthManager
import com.ssafy.travelmate.util.states.LoginState
import com.ssafy.travelmate.ui.theme.TravelMateTheme
import com.ssafy.travelmate.util.enums.EProviders
import com.ssafy.travelmate.util.managers.KakaoAuthManager
import com.ssafy.travelmate.util.managers.NaverAuthManager
import com.ssafy.travelmate.util.managers.preferences.AuthPreferenceManager
import com.ssafy.travelmate.viewmodels.login.LoginViewModel
import kotlinx.coroutines.launch

private const val TAG = "GreetingScreen"
@Preview(showBackground = true)
@Composable
fun GreetingScreenPreview() {
    TravelMateTheme {
        GreetingScreenContent(
            loginState = LoginState.Idle,
            onGoogleLogin = {},
            onNaverLogin = {},
            onKakaoLogin = {},
            onClickLogin = {},
            onClickSignUp = {}
        )
    }
}

@Composable
fun GreetingScreen(
    viewModel: LoginViewModel,
    toHome: () -> Unit,
    toOAuthSignup: (String) -> Unit,
    onClickLogin: () -> Unit,
    onClickSignUp: () -> Unit
) {
    val loginState by viewModel.loginState.collectAsState() //상태 바뀌면 호출

    LaunchedEffect(Unit) {
        /* 로그인 STATE LOADING중이면 다른 화면 띄운다 안그러면 로그인화면창이 뜬다.
        todo : 유저 정보 가져오는 중에 로딩화면 만들기 */
        viewModel.checkAutoLogin()
    }

    LaunchedEffect(loginState) {
        if (loginState is LoginState.Success) {
            val response = (loginState as LoginState.Success).response
            if (response.isNewUser) {
                toOAuthSignup(response.tempToken ?: "")
                //임시 토큰은 signup의 네비게이션 path경로로 사용
            } else {
                // 최초 로그인 시 로컬에 토큰을 저장합니다. (자동 로그인을 위해 필수!)
                AuthPreferenceManager.saveTokens(
                    response.accessToken ?: "",
                    response.refreshToken ?: ""
                )
                toHome()
            }
            viewModel.resetState()
        }
    }

    GreetingScreenContent(
        loginState = loginState,
        onGoogleLogin = { idToken -> viewModel.login(idToken, EProviders.GOOGLE.provider) },
        onNaverLogin = { idToken -> viewModel.login(idToken, EProviders.NAVER.provider) },
        onKakaoLogin = { idToken -> viewModel.login(idToken, EProviders.KAKAO.provider) },
        onClickLogin = onClickLogin,
        onClickSignUp = onClickSignUp
    )
}

@Composable
fun GreetingScreenContent(
    loginState: LoginState,
    onGoogleLogin: (String) -> Unit,
    onNaverLogin: (String) -> Unit,
    onKakaoLogin: (String) -> Unit,
    onClickLogin: () -> Unit,
    onClickSignUp: () -> Unit
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val googleAuthManager = remember { GoogleAuthManager() }
    val kakaoAuthManager = remember { KakaoAuthManager() }
    val naverAuthManager = remember { NaverAuthManager() }
    Column(
        modifier = Modifier.fillMaxSize(),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Spacer(modifier = Modifier.weight(0.15f))

        Text(
            text = "TravelMate",
            color = MaterialTheme.colorScheme.primary,
            style = MaterialTheme.typography.headlineLarge
        )

        Spacer(modifier = Modifier.weight(0.25f))

        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 24.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Button(
                modifier = Modifier.fillMaxWidth(),
                onClick = onClickLogin
            ) {
                Text("로그인")
            }
            Button(
                modifier = Modifier.fillMaxWidth(),
                onClick = onClickSignUp
            ) {
                Text("회원가입")
            }
        }

        Spacer(modifier = Modifier.weight(0.3f))

        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(bottom = 48.dp, start = 24.dp, end = 24.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            val buttonModifier = Modifier.weight(1f)
            GoogleLoginButton(modifier = buttonModifier) {
                scope.launch {
                    val token = googleAuthManager.getIdToken(context)
                    token?.let { onGoogleLogin(it) }

                    Log.d(TAG, " GoogleLogin Token: $token")
                }
            }
            KakaoLoginButton(modifier = buttonModifier) {
                scope.launch {
                    val token = kakaoAuthManager.login(context)

                    token?.let{ onKakaoLogin(it) }
                    Log.d(TAG, "KakaoLogin Token: $token")
                }
            }
            NaverLoginButton(modifier = buttonModifier) {
                scope.launch {
                    val token = naverAuthManager.login(context)
                    token?.let{onNaverLogin(it)}
                    Log.d(TAG, "NaverLogin Token: $token")
                }
            }
        }
        Spacer(modifier = Modifier.weight(0.1f))
        Button(
            colors = ButtonDefaults.buttonColors(containerColor = NaverGreen),
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 24.dp),
            onClick = {
                scope.launch {
                    naverAuthManager.disconnect(context)
                    Log.d("Naver", "Naver:연동 해제 완료")
                }
            }
        ){
            Text(
                color = Color.White,
                text = "네이버 로그아웃"
            )
        }

    }
}
