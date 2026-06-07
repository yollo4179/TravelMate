package com.ssafy.travelmate.screens.homes

import androidx.compose.foundation.layout.*
import androidx.compose.material3.Button
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.ssafy.travelmate.data.RetrofitUtil
import com.ssafy.travelmate.util.events.GlobalEventBus
import com.ssafy.travelmate.util.managers.preferences.AuthPreferenceManager
import kotlinx.coroutines.launch

@Composable
fun HomeScreen(){
    val scope = rememberCoroutineScope()
    
    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text("홈 화면입니다!")
            Spacer(modifier = Modifier.height(16.dp))
            Button(onClick = {
                scope.launch {
                    try {
                        // 서버 로그아웃 호출 (실패해도 로컬 로그아웃은 진행)
                        RetrofitUtil.authService.logout("")
                    } catch (e: Exception) {
                        e.printStackTrace()
                    }
                    AuthPreferenceManager.clearUser()
                    // 전역 이벤트 버스를 통해 로그인 화면으로 이동 publish
                    GlobalEventBus.emitSessionExpired("LOGOUT")
                }
            }) {
                Text("로그아웃")
            }
        }
    }
}
