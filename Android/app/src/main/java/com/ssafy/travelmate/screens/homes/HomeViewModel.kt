package com.ssafy.travelmate.screens.homes

import androidx.lifecycle.ViewModel
import com.ssafy.travelmate.data.repository.MemberRepository

class HomeViewModel(
    repository: MemberRepository // HomeView 밖에서 팩토리로 주입하자
) : ViewModel() {

}