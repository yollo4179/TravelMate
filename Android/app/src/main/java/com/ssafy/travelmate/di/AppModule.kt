package com.ssafy.travelmate.di

import com.ssafy.travelmate.base.MainApplication
import com.ssafy.travelmate.data.db.AppDatabase
import com.ssafy.travelmate.data.repository.MemberRepository
import com.ssafy.travelmate.repositories.AuthRepository
import com.ssafy.travelmate.repositories.KakaoQueryRepository
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object AppModule {

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
    fun provideKakaoQueryRepository(): KakaoQueryRepository {
        return KakaoQueryRepository()
    }
}
