package com.ssafy.travelmate.util.events

import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.asSharedFlow

object GlobalEventBus {
    private val _sessionExpiredEvent = MutableSharedFlow<String>(extraBufferCapacity = 1)
    val sessionExpiredEvent = _sessionExpiredEvent.asSharedFlow()

    fun emitSessionExpired(errorCode: String) {
        _sessionExpiredEvent.tryEmit(errorCode)
    }
}
