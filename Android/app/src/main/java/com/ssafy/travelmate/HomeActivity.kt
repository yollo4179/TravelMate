package com.ssafy.travelmate

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import androidx.navigation.NavHostController
import androidx.navigation.compose.rememberNavController
import com.google.android.material.bottomnavigation.BottomNavigationMenuView
import com.kakao.sdk.common.util.Utility
import com.ssafy.travelmate.ui.theme.TravelMateTheme
import com.ssafy.travelmate.util.ui.UtilTheme
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import com.ssafy.travelmate.screens.homes.HomeScreen
import com.ssafy.travelmate.viewmodels.users.MeViewModel
import androidx.hilt.navigation.compose.hiltViewModel
import dagger.hilt.android.AndroidEntryPoint

@AndroidEntryPoint
class HomeActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()


        setContent {
            TravelMateTheme(dynamicColor = false) {
                TravelMateAppHome()
            }
        }
    }
}

@Composable
fun TravelMateAppHome(
    navController : NavHostController = rememberNavController(),
    backgroundBrush : Brush = UtilTheme().generateGradientBackground(),
    context : ComponentActivity = HomeActivity()
    ){



    Scaffold(
        modifier = Modifier.fillMaxSize(),
        bottomBar = { BottomNavigationMenuView(
            navController, context) }

    ) { innerPadding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(backgroundBrush)
                .padding(innerPadding)
        ){
            NavigatedHomeScreens(
                navController = navController,
            )

        }

    }
}
@Composable
fun BottomNavigationMenuView(
    navController : NavHostController,
    context : Context
) {
    val items = listOf("홈", "알림", "나")
    var selectedItem by remember { mutableStateOf(0) }

    NavigationBar {
        items.forEachIndexed { index, item ->
            NavigationBarItem(
                icon = {
                    when (item) {
                        "홈" -> Icon(Icons.Filled.Home, contentDescription = item)
                        "나" -> Icon(Icons.Filled.Search, contentDescription = item)
                        "알림" -> Icon(Icons.Filled.Settings, contentDescription = item) // 예시
                    }
                },
                label = { Text(item) },
                selected = selectedItem == index,
                onClick = {
                    selectedItem = index
                    // TODO: navController를 이용해 해당 아이템의 목적지로 이동
                     navController.navigate(item.lowercase()) {
                        popUpTo(navController.graph.startDestinationId)
                        launchSingleTop = true
                     }
                })
        }
    }
}

@Composable
fun NavigatedHomeScreens(
    navController: NavHostController
){
    val meViewModel: MeViewModel = hiltViewModel()

    NavHost(
        navController = navController,
        startDestination = "홈" // from bottom nav
    ) {
        composable("홈") {
            val context = LocalContext.current
            HomeScreen(
                meViewModel = meViewModel,
                onLogout = {
                    val intent = Intent(context, MainActivity::class.java)
                    intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
                    context.startActivity(intent)
                }
            )
        }
        composable("알림") {
            Box(modifier = Modifier.fillMaxSize()) {
                Text("알림 화면", modifier = Modifier.padding(16.dp))
            }
        }
        composable("나") {
            com.ssafy.travelmate.screens.me.MeScreen(viewModel = meViewModel)
        }
    }
}