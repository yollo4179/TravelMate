package com.ssafy.travelmate.apis

import com.ssafy.travelmate.data.remote.dto.requests.plan.GeneratePlanRequest
import com.ssafy.travelmate.data.remote.dto.requests.plan.PlanContext
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.POST
import retrofit2.http.Path

enum class PlanningJobStatus { QUEUED, RUNNING, SUCCEEDED, FAILED }

data class PlanningJobResponse(
    val jobId: String,
    val status: PlanningJobStatus,
    val statusUrl: String,
    val planId: Long? = null,
    val errorMessage: String? = null
)

data class DraftPin(
    val placeId: Long,
    val name: String,
    val latitude: Double,
    val longitude: Double,
    val stayMinutes: Int,
    val sequence: Int
)

data class PlanResponse(
    val planId: Long,
    val context: PlanContext,
    val title: String,
    val pins: List<DraftPin>,
    val warnings: List<String>
)

interface PlanApi {
    @POST("api/v1/plans/generations")
    suspend fun generate(
        @Header("Idempotency-Key") idempotencyKey: String,
        @Body request: GeneratePlanRequest
    ): PlanningJobResponse

    @POST("api/v1/plans")
    suspend fun create(
        @Header("Idempotency-Key") idempotencyKey: String,
        @Body request: GeneratePlanRequest
    ): PlanResponse

    @GET("api/v1/planning-jobs/{jobId}")
    suspend fun job(@Path("jobId") jobId: String): PlanningJobResponse

    @GET("api/v1/plans/{planId}")
    suspend fun plan(@Path("planId") planId: Long): PlanResponse
}
