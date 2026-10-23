package com.ssafy.travelmate.di

import com.ssafy.travelmate.base.MainApplication
import com.ssafy.travelmate.data.db.AppDatabase
import com.ssafy.travelmate.data.repository.MemberRepository
import com.ssafy.travelmate.repositories.AuthRepository
import com.ssafy.travelmate.repositories.PlaceSearchRepository
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton
import com.ssafy.travelmate.apis.PlaceSearchApi
import okhttp3.OkHttpClient
import java.util.concurrent.TimeUnit

@Module
@InstallIn(SingletonComponent::class)
object AppModule {

    @Provides
    @Singleton
    fun provideAuthenticatedPlanningApi(): com.ssafy.travelmate.apis.PlanApi =
        MainApplication.retrofit.create(com.ssafy.travelmate.apis.PlanApi::class.java)

    @Provides
    @Singleton
    fun provideAppDatabase(): AppDatabase {
        return MainApplication.database
    }

    @Provides
    @Singleton
    fun provideMemberRepository(db: AppDatabase): MemberRepository {
        return MemberRepository(db)
    }

    @Provides
    @Singleton
    fun provideAuthRepository(): AuthRepository {
        return AuthRepository()
    }

    @Provides
    @Singleton
    fun providePlaceSearchApi(): PlaceSearchApi {
        val retrofit = MainApplication.retrofit
        // 모델의 첫 로딩은 일반 로그인 요청보다 오래 걸릴 수 있다.
        val searchClient = (retrofit.callFactory() as OkHttpClient).newBuilder()
            .readTimeout(60, TimeUnit.SECONDS)
            .callTimeout(90, TimeUnit.SECONDS)
            .build()
        return retrofit.newBuilder()
            .client(searchClient)
            .build()
            .create(PlaceSearchApi::class.java)
    }

    @Provides
    @Singleton
    fun providePlaceSearchRepository(api: PlaceSearchApi): PlaceSearchRepository {
        return PlaceSearchRepository(api)
    }
}
