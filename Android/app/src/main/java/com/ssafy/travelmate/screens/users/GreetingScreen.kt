package com.ssafy.travelmate.screens.users

import androidx.compose.foundation.layout.*
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.ssafy.travelmate.components.GoogleLoginButton
import com.ssafy.travelmate.components.KakaoLoginButton
import com.ssafy.travelmate.components.NaverLoginButton
import com.ssafy.travelmate.ui.theme.TravelMateTheme
import com.ssafy.travelmate.util.enums.EProviders
import com.ssafy.travelmate.util.managers.GoogleAuthManager
import com.ssafy.travelmate.util.managers.KakaoAuthManager
import com.ssafy.travelmate.util.managers.NaverAuthManager
import com.ssafy.travelmate.util.states.LoginState
import com.ssafy.travelmate.viewmodels.greeting.GreetingViewModel

private const val TAG = "GreetingScreen"

@Preview(showBackground = true)
@Composable
fun GreetingScreenPreview() {
    TravelMateTheme {
        GreetingIdleContent(
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
    viewModel: GreetingViewModel,
    toHome: () -> Unit,
    toOAuthSignup: (String) -> Unit,
    onClickLogin: () -> Unit,
    onClickSignUp: () -> Unit
) {
    val loginState by viewModel.loginState.collectAsState()
    val context = LocalContext.current
    val googleAuthManager = remember { GoogleAuthManager() }
    val kakaoAuthManager = remember { KakaoAuthManager() }
    val naverAuthManager = remember { NaverAuthManager() }

    LaunchedEffect(Unit) {
        viewModel.checkAutoLogin()
    }

    LaunchedEffect(loginState) {
        if (loginState is LoginState.LoggedIn) {
            val response = (loginState as LoginState.LoggedIn).response
            if (response.isNewUser) {
                toOAuthSignup(response.tempToken)
            } else {
                toHome()
            }
        }
    }

    when (loginState) {
        is LoginState.LoggingIn, is LoginState.LoggedIn-> {

            GreetingLoadingContent()
        }
        is LoginState.Failed -> {
            GreetingFailedContent(
                message = (loginState as LoginState.Failed).message,
                onRetry = { viewModel.resetState() }
            )
        }
        is LoginState.Idle -> {
            //Text(text = "LoggedIn333333333333333", color  = Color.Red)
            GreetingIdleContent(
                onGoogleLogin = {
                    viewModel.login(EProviders.GOOGLE.provider) {
                        googleAuthManager.getIdToken(context)
                    }
                },
                onKakaoLogin = {
                    viewModel.login(EProviders.KAKAO.provider) {
                        kakaoAuthManager.login(context)
                    }
                },
                onNaverLogin = {
                    viewModel.login(EProviders.NAVER.provider) {
                        naverAuthManager.login(context)
                    }
                },
                onClickLogin = onClickLogin,
                onClickSignUp = onClickSignUp
            )
        }
    }
}

@Composable
fun GreetingLoadingContent() {
    Box(
        modifier = Modifier.fillMaxSize(),
        contentAlignment = Alignment.Center
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            CircularProgressIndicator()
            Spacer(modifier = Modifier.height(16.dp))
            Text(
                text = "로그인 중...",
                style = MaterialTheme.typography.bodyLarge
            )
        }
    }
}

@Composable
fun GreetingFailedContent(
    message: String,
    onRetry: () -> Unit
) {
    Box(
        modifier = Modifier.fillMaxSize(),
        contentAlignment = Alignment.Center
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            Text(
                text = "로그인 실패",
                style = MaterialTheme.typography.headlineMedium,
                color = MaterialTheme.colorScheme.error
            )
            Text(
                text = message,
                style = MaterialTheme.typography.bodyMedium
            )
            Button(onClick = onRetry) {
                Text("다시 시도")
            }
        }
    }
}

@Composable
fun GreetingIdleContent(
    onGoogleLogin: () -> Unit,
    onNaverLogin: () -> Unit,
    onKakaoLogin: () -> Unit,
    onClickLogin: () -> Unit,
    onClickSignUp: () -> Unit
) {
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
            GoogleLoginButton(modifier = buttonModifier) { onGoogleLogin() }
            KakaoLoginButton(modifier = buttonModifier) { onKakaoLogin() }
            NaverLoginButton(modifier = buttonModifier) { onNaverLogin() }
        }

        Spacer(modifier = Modifier.weight(0.1f))
    }
}
