package com.ssafy.travelmate

import android.os.Bundle
import android.util.Log
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavController
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.kakao.sdk.common.KakaoSdk
import com.kakao.sdk.common.util.Utility
import com.navercorp.nid.NaverIdLoginSDK
import com.ssafy.travelmate.apis.AuthApi
import com.ssafy.travelmate.data.RetrofitUtil
import com.ssafy.travelmate.repositories.AuthRepository
import com.ssafy.travelmate.screens.homes.HomeScreen
import com.ssafy.travelmate.screens.users.GreetingScreen
import com.ssafy.travelmate.screens.users.LoginScreen
import com.ssafy.travelmate.screens.users.OAuthNicknameScreen
import com.ssafy.travelmate.screens.users.SignupScreen
import com.ssafy.travelmate.util.ui.UtilTheme
import com.ssafy.travelmate.ui.theme.TravelMateTheme
import com.ssafy.travelmate.util.events.GlobalEventBus
import com.ssafy.travelmate.viewmodels.login.LoginViewModel

private const val TAG = "MainActivity"
class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        /*For Debug*/
        val keyHash = Utility.getKeyHash(this)
        Log.d("keyhash","keyhash:${keyHash}");

        setContent {
            TravelMateTheme(dynamicColor = false) {
                TravelMateApp()
            }
        }
    }
}

@Composable
fun TravelMateApp() {
    val navController = rememberNavController()
    val backgroundBrush = UtilTheme().generateGradientBackground()
    val context = androidx.compose.ui.platform.LocalContext.current

    LaunchedEffect (Unit) {
        GlobalEventBus.sessionExpiredEvent.collect { errorCode ->
            when(errorCode) {
                "ERR_TEMP_TOKEN_EXPIRED" -> {
                    Toast.makeText(context, "가입 시간이 초과되었습니다. 처음부터 다시 시도해주세요.", Toast.LENGTH_SHORT).show()
                }
                else -> {
                    Toast.makeText(context, "로그인이 만료되었습니다. 다시 로그인해주세요.", Toast.LENGTH_SHORT).show()
                }
            }
            navController.navigateToGreeting()
        }
    }

    // Scafold는 fab, 상단 바 하단바를 제공 / 화면의 뼈대
    Scaffold(modifier = Modifier.fillMaxSize()) { innerPadding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(backgroundBrush)
                .padding(innerPadding)
        ){
            NavigatedScreens(
                navController = navController,
            )

        }
    }
}

@Composable
fun NavigatedScreens(navController: NavHostController){

    // `레포지토리`를 사용하여 ViewModel 생성에 필요한 의존성 준비
    val repository = remember { AuthRepository() }
    //팩토리임니다 .
    val loginViewModel: LoginViewModel = viewModel(
        factory = object : ViewModelProvider.Factory {
            override fun <T : ViewModel> create(modelClass: Class<T>): T {
                return LoginViewModel(repository) as T
            }
        }
    )

    NavHost(
        navController = navController,
        startDestination = "greeting",
    ){
        composable("greeting"){
            GreetingScreen(
                viewModel = loginViewModel,
                toHome = { navController.navigateToHome() },
                toOAuthSignup = { tempToken -> navController.navigateToOAuthSignup(tempToken) },
                onClickLogin = {navController.navigate("login")},
                onClickSignUp = {navController.navigate("signup")}
            )
        }
        composable("login"){
            LoginScreen(
                toHome = {navController.navigateToHome()},
                toGreeting = {navController.navigateToSignUp()}
            )

        }
        composable("oauth_signup/{tempToken}"){ backStackEntry -> //greetingScreen에서 받아서 path에 넣는다.
            val tempToken = backStackEntry.arguments?.getString("tempToken") ?: ""
            OAuthNicknameScreen(
                tempToken = tempToken,
                viewModel = loginViewModel,
                toHome = { navController.navigateToHome() }
            )
        }
        composable("signup"){
            SignupScreen(
                toGreeting = {navController.navigateToGreeting()},
                toLogin = {navController.navigateToLogin()}
            )
        }
        composable("home"){
            HomeScreen()
        }

    }
}

@Composable
fun Greeting(name: String, modifier: Modifier = Modifier) {
    Text(
        text = "Welcome to $name!",
        modifier = modifier
    )
}

/***********navigateion 람다 함수 ***********/
fun NavController.navigateToHome() {
    //백스택 뺴버림
    this.navigate("home") {
        launchSingleTop = true
        popUpTo("greeting") { inclusive = true } //이전의 화면기록을 지운다
    }
}
fun NavController.navigateToGreeting() {
    this.navigate("greeting") {
        launchSingleTop = true
    }
}
fun NavController.navigateToSignUp() {
    this.navigate("signup") {
        launchSingleTop = true;
    }
}
fun NavController.navigateToLogin() {
    this.navigate("login") {
        launchSingleTop = true;
    }
}
fun NavController.navigateToOAuthSignup(tempToken: String) {
    this.navigate("oauth_signup/$tempToken") {
        launchSingleTop = true
    }
}
/***********navigateion 람다 함수 ***********/
