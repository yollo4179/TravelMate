package com.ssafy.travelmate.data.db

import androidx.room.Dao
import androidx.room.Delete
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Update
import kotlinx.coroutines.flow.Flow

@Dao
interface MemberDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE) //중복 허용
    suspend fun insert(member: Member)

    @Query("SELECT * FROM members")
    fun getAll(): Flow<List<Member>> //일단 얘는 빨대를 꽂아두고 서버에서 정보가 바뀌면 그때 처리한다.
    
    @Query("SELECT * FROM members WHERE uid = :uid")
    fun getMember(uid: String): Flow<Member?>

    @Query("SELECT EXISTS(SELECT 1 FROM members WHERE uid = :uid)")
    suspend fun exists(uid: String): Boolean

    @Query("DELETE FROM members")
    suspend fun clear()
    
    @Update(onConflict = OnConflictStrategy.REPLACE)
    suspend fun update(member: Member)
    
    @Delete
    suspend fun delete(member: Member)

    /*******************복합 쿼리문 join + 내아이디 가 조건 ************************/

    /*********친구 가져오기 *************/

    /**********방 멤버 가져오기 **********/

}