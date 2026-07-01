package com.ssafy.travelmate.data.repository

import com.ssafy.travelmate.data.db.AppDatabase
import com.ssafy.travelmate.data.db.Member
import kotlinx.coroutines.flow.Flow

class MemberRepository(
    private val db : AppDatabase
) {


    suspend fun insertMember (member : Member){
        db.memberDao().insert(member)
    }
    fun getMember (uid : String) : Flow<Member?> {
        return db.memberDao().getMember(uid)
    }
    fun getAllMember () : Flow<List<Member>> {
        return db.memberDao().getAll()
    }
    suspend fun exists(uid: String): Boolean {
        return db.memberDao().exists(uid)
    }

    suspend fun clearMember (){
        db.memberDao().clear()
    }
    suspend fun updateMember (member : Member){
        db.memberDao().update(member)
    }
    suspend fun deleteMember (member : Member){
        db.memberDao().delete(member)
    }
}

