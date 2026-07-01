package com.ssafy.travelmate.viewmodels.users

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ssafy.travelmate.data.db.Member
import com.ssafy.travelmate.data.repository.MemberRepository

import com.ssafy.travelmate.util.managers.preferences.AuthPreferenceManager
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class MeViewModel @Inject constructor(
    private val memberRepository: MemberRepository
) : ViewModel() {

    private val _currentUser = MutableStateFlow<Member?>(null)
    val currentUser = _currentUser.asStateFlow()

    init {
        loadUser()
    }

    private fun loadUser() {
        val uid = AuthPreferenceManager.getUid()
        if (uid != null) {
            viewModelScope.launch {
                memberRepository.getMember(uid).collect { member ->
                    _currentUser.value = member
                }
            }
        }
    }
}
