package com.yollo.TravelMate.domain.user.entity;

import lombok.AccessLevel;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import java.time.LocalDateTime;

import org.springframework.data.annotation.CreatedDate;
import org.springframework.data.annotation.LastModifiedDate;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
@Entity// JPA가 관리하는 엔티티임을 명시 (DB 테이블과 매핑)
@Table(name = "users") // DB 테이블 이름을 "users"로 지정
@Getter @Setter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
@AllArgsConstructor
@Builder //체이닝 제공
public class User {
	//자바 객체(Entity)에도 어떤 필드가 DB의 PK와 매핑되는지 알려줘야
	//JPA는 영속성 컨텍스트(1차 캐시)라는 곳에 객체를 저장할 때 이 @Id 값을 Key로 사용
	
	@Id
	@GeneratedValue
	private Long userId;
	
	@Column(nullable = false, unique = true)
	private String email;
	
	// 카카오나 외부 api 관할이면 비워둡니다. 해당 앱의 관할이 아님
	private String password ; 
	
	@Column(nullable = false, unique = true)
	private String nickname;
	
	// 카카오나 외부 api 관할이면 비워둡니다.//사실 필요 없을 수도..
	@Column(nullable = true)
	private String phoneNumber; 
	
	//유저의 맘대로 , 설정안하면 기본 url
	@Column(nullable = true)
	private String profileImgUrl;
	
	@Column(nullable = true)
	private String role;
	
	@Column(nullable = false)
	private String status;
	
	@Column(nullable = false)
    private String provider;
	
	@CreatedDate
    @Column(updatable = false)
	private LocalDateTime createdAt;
	
	@LastModifiedDate
	private LocalDateTime updatedAt;
	
	public void updateProfile(String nickname, String profileImage) {
        this.nickname = nickname;
        this.profileImgUrl = profileImage;
    }
	
}
