package com.yollo.TravelMate.jwt;

import java.nio.charset.StandardCharsets;
import java.security.Key;
import java.util.Base64;
import java.util.Date;
import java.util.List;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.stereotype.Component;

import com.yollo.TravelMate.domain.user.entity.User;
import com.yollo.TravelMate.domain.user.service.UserService;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.SignatureAlgorithm;
import io.jsonwebtoken.io.Decoders;
import io.jsonwebtoken.security.Keys;
import jakarta.annotation.PostConstruct;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;

@Component
@RequiredArgsConstructor
public class JwtTokenProvider {
	
	private static final org.slf4j.Logger log = org.slf4j.LoggerFactory.getLogger(JwtTokenProvider.class);

	
	@Value("${jwt.secret}") 
	private String secretKey;
	private Key key;
	
	@Value("${jwt.access-expiration}") 
	private  long ACCESS_TOKEN_VALID_MS ;
	
	@Value("${jwt.refresh-expiration}")
	private  long REFRESH_TOKEN_VALID_MS ;
	
	@Autowired
	private final UserService userService;
	
	/*PostConstruct: 한번만 실행 초기화*/
	@PostConstruct protected void init() {
		/*초기화 :  secretKey를 Base64로 변환 */
		log.debug("[init] JwtTokenProvider: Start init secretKey:${}",secretKey);
		secretKey = Base64.getEncoder().encodeToString(secretKey.getBytes(StandardCharsets.UTF_8));		
		log.info("[init] JwtTokenProvider: Finish init secretKey${}",secretKey);
		byte[] keyBytes = Decoders.BASE64.decode(secretKey);
		this.key = Keys.hmacShaKeyFor(keyBytes);
		
	}
	
	private String createToken( String userUid , List<String>roles,long expireTime) {
		
		
		Claims claims = Jwts.claims().setSubject(userUid);
		claims.put("roles", roles);
		
		Date now =new Date();
		
		String token = Jwts.builder()
				.setClaims(claims)
				.setIssuedAt(now)
				.setExpiration(new Date(now.getTime()+expireTime))
				.signWith(key,SignatureAlgorithm.HS256) 
		        .compact();
		
		
		  return token;
	}
	public String createAccessToken(String userPk, List<String> roles) {
        return createToken(userPk, roles, ACCESS_TOKEN_VALID_MS);
    }

    public String createRefreshToken(String userPk, List<String> roles) {
        return createToken(userPk, roles, REFRESH_TOKEN_VALID_MS); 
    }
    
    public Authentication getAuthentication(String token) {
        // UserDetails를 가져와서 시큐리티 인증 객체 생성
    	UserDetails user = userService.loadUserByUsername(this.getUsername(token));

    	return new UsernamePasswordAuthenticationToken(user, "", user.getAuthorities());
    }
    
    public String getUsername(String token) {
        // setSigningKey(secretKey) -> setSigningKey(key)로 변경 (최신 방식)
        return Jwts.parserBuilder()
                .setSigningKey(key)
                .build()
                .parseClaimsJws(token)
                .getBody()
                .getSubject();
    }
    
    public String resolveToken(HttpServletRequest request) {
        // 헤더 이름을 "X-AUTH-TOKEN"으로 쓰기로 하셨군요!
        return request.getHeader("X-AUTH-TOKEN");
    }
    
    public boolean validateToken(String token) {
        log.info("[validateToken] 토큰 유효 체크 시작");
        try {
            // parseClaimsJws 메서드가 에러 없이 실행되면 유효한 토큰임
            Jwts.parserBuilder().setSigningKey(key).build().parseClaimsJws(token);
            return true;
        } catch (Exception e) {
            log.error("[validateToken] 유효하지 않은 토큰: {}", e.getMessage());
            return false;
        }
    }
}
