package com.ssafy.travelmate.data.db

import androidx.room.Database
import androidx.room.RoomDatabase
import com.ssafy.travelmate.data.db.Member
import com.ssafy.travelmate.data.db.MemberDao

@Database(
    entities =
        [Member::class,]
    ,version = 1 )
abstract class AppDatabase: RoomDatabase() {

    abstract fun  memberDao(): MemberDao

}