package com.yollo.TravelMate.domain.user.entity;

import lombok.AccessLevel;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import java.util.stream.Collectors;

import org.springframework.data.annotation.CreatedDate;
import org.springframework.data.annotation.LastModifiedDate;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.userdetails.UserDetails;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import org.springframework.data.jpa.domain.support.AuditingEntityListener;
import jakarta.persistence.EntityListeners;

@Entity// JPA가 관리하는 엔티티임을 명시 (DB 테이블과 매핑)
@EntityListeners(AuditingEntityListener.class)
@Table(name = "users") // DB 테이블 이름을 "users"로 지정
@Getter @Setter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
@AllArgsConstructor
@Builder //체이닝 제공
public class User implements UserDetails {
	//자바 객체(Entity)에도 어떤 필드가 DB의 PK와 매핑되는지 알려줘야
	//JPA는 영속성 컨텍스트(1차 캐시)라는 곳에 객체를 저장할 때 이 @Id 값을 Key로 사용
	
	@Id
	@Column(name = "uid", length = 36)
	private String uid;
	
	
	@Column(name = "user_id",nullable = false, unique = true)
	private String userId;
	
	@Column(name = "email",nullable = false, unique = true)
	private String email;
	
	// 카카오나 외부 api 관할이면 비워둡니다. 해당 앱의 관할이 아님
	@Column(name = "password")
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
	
	@Column(name = "provider_id",nullable =true)
	private String providerId ;
	
	
	@CreatedDate
    @Column(updatable = false)
	private LocalDateTime createdAt;
	
	
	@LastModifiedDate
	private LocalDateTime updatedAt;
	
	
	public void updateProfile(String nickname, String profileImage) {
        this.nickname = nickname;
        this.profileImgUrl = profileImage;
    }

	
	// --- UserDetails 필수 구현 메서드 ---

    @Override
    public Collection<? extends GrantedAuthority> getAuthorities() {
        // 단일 role 필드를 Spring Security 권한 객체 리스트로 변환
        List<GrantedAuthority> authorities = new ArrayList<>();
        authorities.add(new SimpleGrantedAuthority(this.role));
        return authorities;
    }

    @Override
    public String getUsername() {
        // Security가 유저를 식별할 수 있는 값 (이메일 혹은 UID)
        return this.email; 
    }

    @Override
    public String getPassword() {
        return this.password;
    }

    // 계정 상태 관리 (모두 true로 설정해야 로그인이 가능합니다)
    @Override
    public boolean isAccountNonExpired() { return true; }

    @Override
    public boolean isAccountNonLocked() { return true; }

    @Override
    public boolean isCredentialsNonExpired() { return true; }

    @Override
    public boolean isEnabled() { return true; }

   
	
}
