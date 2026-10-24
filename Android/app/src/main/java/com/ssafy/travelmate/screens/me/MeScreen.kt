package com.ssafy.travelmate.screens.me

import androidx.compose.runtime.Composable
import com.ssafy.travelmate.viewmodels.users.MeViewModel
import androidx.hilt.navigation.compose.hiltViewModel
import com.ssafy.travelmate.viewmodels.search.SearchViewModel
import com.ssafy.travelmate.viewmodels.search.TravelPlanningViewModel

@Composable
fun MeScreen(
    viewModel: MeViewModel,
    searchViewModel: SearchViewModel = hiltViewModel(),
    planningViewModel: TravelPlanningViewModel = hiltViewModel()
){
    TravelPlanningScreen(planningViewModel, searchViewModel)
}
