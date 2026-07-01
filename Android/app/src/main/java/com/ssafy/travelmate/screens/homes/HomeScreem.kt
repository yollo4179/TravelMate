package com.ssafy.travelmate.screens.homes

import androidx.compose.foundation.layout.*
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.ssafy.travelmate.data.RetrofitUtil
import com.ssafy.travelmate.util.events.GlobalEventBus
import com.ssafy.travelmate.util.managers.preferences.AuthPreferenceManager
import kotlinx.coroutines.launch

import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue

@Composable
fun HomeScreen(
    meViewModel: com.ssafy.travelmate.viewmodels.users.MeViewModel,
    onLogout: () -> Unit = {}
){
    val currentUser by meViewModel.currentUser.collectAsState()
    val scope = rememberCoroutineScope()

    Text(
        text = "Home Screen",
        color =Color.Red,
        style = MaterialTheme.typography.titleLarge
    )

    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            if (currentUser != null) {
                Text("안녕하세요, ${currentUser?.name}님!",
                    style = MaterialTheme.typography.headlineMedium,
                    color =Color.Red
                )
                Text(
                    "이메일: ${currentUser?.email}",
                            color =Color.Red
                )
            } else {
                Text("유저 정보를 불러오는 중...")
            }
            Spacer(modifier = Modifier.height(32.dp))
            Button(onClick = {
                scope.launch {
                    try {

                        RetrofitUtil.authService.logout("")
                    } catch (e: Exception) {
                        e.printStackTrace()
                    }
                    AuthPreferenceManager.clearUser()
                    // 전역 이벤트 버스를 통해 로그인 화면으로 이동 publish
                    GlobalEventBus.emitSessionExpired("LOGOUT")
                    onLogout()
                }
            }) {
                Text("로그아웃")
            }
        }
    }
}
