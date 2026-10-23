package com.ssafy.travelmate.repositories

import com.ssafy.travelmate.apis.PlanApi
import com.ssafy.travelmate.apis.PlanResponse
import com.ssafy.travelmate.apis.PlanningJobStatus
import com.ssafy.travelmate.data.remote.dto.requests.plan.GeneratePlanRequest
import com.ssafy.travelmate.util.states.PlanningMode
import kotlinx.coroutines.delay
import kotlinx.coroutines.withTimeout
import javax.inject.Inject

class TravelPlanningRepository @Inject constructor(
    private val api: PlanApi
) {

    suspend fun submit(
        request: GeneratePlanRequest,
        mode: PlanningMode,
        idempotencyKey: String
    ): PlanResponse {
        if (mode == PlanningMode.MANUAL) return api.create(idempotencyKey, request)
        var job = api.generate(idempotencyKey, request)
        return withTimeout(300_000) {
            while (job.status == PlanningJobStatus.QUEUED || job.status == PlanningJobStatus.RUNNING) {
                delay(1500)
                job = api.job(job.jobId)
            }
            check(job.status == PlanningJobStatus.SUCCEEDED) {
                job.errorMessage ?: "일정을 생성하지 못했습니다. 조건을 확인해 주세요."
            }
            api.plan(requireNotNull(job.planId))
        }
    }
}
