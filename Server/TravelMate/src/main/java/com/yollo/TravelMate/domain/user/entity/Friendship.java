package com.yollo.TravelMate.domain.user.entity;

import jakarta.persistence.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Entity
@Table(name = "friendships")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class Friendship {
	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	@Column(name = "friendship_id")
	private Long friendshipId; //pk

	@ManyToOne(fetch = FetchType.LAZY)
	@JoinColumn(name = "user_id", referencedColumnName = "uid", nullable = false)
	private User user;	//fk

	@ManyToOne(fetch = FetchType.LAZY)
	@JoinColumn(name = "friend_id", referencedColumnName = "uid", nullable = false)
	private User friend;	//fk

	@Column(length = 20)
	private String status; // PENDING, ACCEPTED, REJECTED
}
