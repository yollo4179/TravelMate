package com.ssafy.travelmate.screens.users

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.ssafy.travelmate.util.states.LoginState
import com.ssafy.travelmate.viewmodels.login.LoginViewModel

@Composable
fun OAuthNicknameScreen(
    tempToken: String,
    viewModel: LoginViewModel,
    toHome: () -> Unit
){
    var nickname by remember { mutableStateOf("") }
    val loginState by viewModel.loginState.collectAsState()

    LaunchedEffect(loginState) {
        if (loginState is LoginState.Success) {
            val response = (loginState as LoginState.Success).response
            com.ssafy.travelmate.util.managers.preferences.AuthPreferenceManager.saveTokens(
                response.accessToken ?: "",
                response.refreshToken ?: ""
            )
            toHome()
            viewModel.resetState()
        }
    }

    Column(
        modifier = Modifier.fillMaxSize().padding(16.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text("추가 정보 입력", style = MaterialTheme.typography.headlineMedium)
        Spacer(modifier = Modifier.height(16.dp))
        OutlinedTextField(
            value = nickname,
            onValueChange = { nickname = it },
            label = { Text("닉네임") }
        )
        Spacer(modifier = Modifier.height(16.dp))
        Button(onClick = { viewModel.signupOauth(nickname, tempToken) }) {
            Text("가입 완료")
        }
    }
}