package com.ssafy.travelmate.screens.me

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

// @Preview
// @Composable
// fun meScreenPreview(){
//     MeScreen(viewModel = /* mock viewmodel */)
// }

import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import com.ssafy.travelmate.components.MapContent
import com.ssafy.travelmate.viewmodels.users.MeViewModel

@Composable
fun MeScreen(
    viewModel: MeViewModel
){
    val currentUser by viewModel.currentUser.collectAsState()

    Text(
        text = "마이페이지 (이름: ${currentUser?.name ?: "로딩중"})",
        color =Color.Red,
        style = MaterialTheme.typography.titleLarge
    )
    MapContent(modifier =  Modifier.fillMaxSize());
}