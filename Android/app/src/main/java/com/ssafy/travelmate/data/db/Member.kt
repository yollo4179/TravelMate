package com.ssafy.travelmate.data.db

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

//Retrofit이면 Table
@Entity(
    tableName = "members",
    indices = [Index(value = ["uid"], unique = true)]
)
data class Member (

    @PrimaryKey
    val uid: String,
    val name: String,
    val email :String,
    @ColumnInfo(name = "profile_image_url")
    val profileImageUrl :String, //사진을 내 프로필에서 가져와서 서버로 보낸다? 컨텐트 프로바이더?
)