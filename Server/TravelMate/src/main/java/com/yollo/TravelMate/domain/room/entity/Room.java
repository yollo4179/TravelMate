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
@Table(name = "rooms")
@Getter 
@Setter
@NoArgsConstructor 
@AllArgsConstructor
@Builder
public class Room {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	@Column(name = "room_id")
	private Long roomId;  			//PK

	@Column(nullable = false, length = 100)
    private String title;			//title

	@Column(columnDefinition = "TEXT")
    private String description;		//방 설명

	@Column(length = 50)
    private String category;		//방의 카테고리

	@Column(length = 100)
    private String pass;			//방 비번

	@Column(name = "is_private")
    private Boolean isPrivate;		//방의 접근 권한

	
	/*FK: 여러 개의 방은 1명에게 속한다.*/
	@ManyToOne(fetch = FetchType.LAZY) /*** 호스트의 데이터가 필요한 시점에만 DB를 조회 ***/
	@JoinColumn(name = "host_id", referencedColumnName = "uid", nullable = false)
    private User host;			//FK

	@Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;

	@PrePersist
	protected void onCreate() {
		this.createdAt = LocalDateTime.now();
		if (this.isPrivate == null) {
			this.isPrivate = false;
		}
	}
}
