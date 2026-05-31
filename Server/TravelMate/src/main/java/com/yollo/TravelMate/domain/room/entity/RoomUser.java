package com.yollo.TravelMate.domain.room.entity;

import com.yollo.TravelMate.domain.user.entity.User;
import jakarta.persistence.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import java.time.LocalDateTime;

@Entity
@Table(name = "room_user")
@Getter 
@Setter
@NoArgsConstructor 
@AllArgsConstructor
@Builder
public class RoomUser {
	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	@Column(name = "participant_id")
	private Long participantId;  //PK

	/*여러 명의 참여자는 하나의 방에 종속된다.*/
	@ManyToOne(fetch = FetchType.LAZY)
	@JoinColumn(name = "room_id", nullable = false)
    private Room room;		//FK

	
	/*참여자의 uid로 조인 가능 -> 한명의 참여자는 여러 Room의 Participants로서 존재한다.*/
	@ManyToOne(fetch = FetchType.LAZY)
	@JoinColumn(name = "user_id", referencedColumnName = "uid", nullable = false)
    private User user;		//FK

	
	
	@Column(name = "role_as", length = 10)
    private String roleAs; // ADMIN, USER

	@Column(length = 10)
    private String status; // ACTIVE, LEFT, BANNED

	@Column(name = "joined_at", updatable = false)
    private LocalDateTime joinedAt;

	@PrePersist
	protected void onCreate() {
		this.joinedAt = LocalDateTime.now();
		if (this.roleAs == null) {
			this.roleAs = "USER";
		}
		if (this.status == null) {
			this.status = "ACTIVE";
		}
	}
}
