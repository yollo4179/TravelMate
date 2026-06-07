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
import io.jsonwebtoken.ExpiredJwtException;
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

	public static  enum ERole{
		
		USER("ROLE_BASE"),
		ADMIN("ROLE_ADMIN");
		private final String value ; 
		
		ERole(String value){
			this.value = value;
		}
		public String getValue() {
			return value; 
		}
	}
	
	
	@Value("${jwt.secret}") 
	private String secretKey;
	private Key key;
	
	@Value("${jwt.access-expiration}") 
	private  long ACCESS_TOKEN_VALID_MS ;
	
	@Value("${jwt.refresh-expiration}")
	private  long REFRESH_TOKEN_VALID_MS ;
	
	
	
	/*PostConstruct: 한번만 실행 + 초기화*/
	@PostConstruct protected void init() {
		
		log.debug("[init] JwtTokenProvider: Start init secretKey:${}",secretKey);
		secretKey = Base64.getEncoder().encodeToString(secretKey.getBytes(StandardCharsets.UTF_8));		
		log.info("[init] JwtTokenProvider: Finish init secretKey${}",secretKey);
		/* 시크릿키 Base64로 인코딩 완료*/
		
		
		byte[] keyBytes = Decoders.BASE64.decode(secretKey);
		/*바이트로 디코딩*/
		
		this.key = Keys.hmacShaKeyFor(keyBytes);
		/*SecretKey가 충분히 긴지 검중+ java.security.Key 객체 반환 */
		/*key는 Jwts.builder().signWith(key) 호출할 때 강력한 암호화 서명*/
		
	}
	
	private String createToken( String userUid , String  role,long expireTime, String tokenType) {
		
		
		Claims claims = Jwts.claims().setSubject(userUid);
		claims.put("roles", role);
		claims.put("token_type", tokenType);
		/*Payload(내용)에 담길 제이슨 데이터 묶음을 생성하는 메서드 + 권한 추가 +키는 uid */
		
		Date now =new Date();
		
		String token = Jwts.builder()
				.setClaims(claims)
				.setIssuedAt(now)
				.setExpiration(new Date(now.getTime()+expireTime))
				.signWith(key,SignatureAlgorithm.HS256) //발행
		        .compact();
		
		
		return token;
	}
	public String createTempToken(String providerId, String provider, String email) {
	   
	    long TEMP_TOKEN_VALID_TIME = 5 * 60 * 1000L;
	    Date now = new Date();

	    return Jwts.builder()
	            .claim("providerId", providerId) 
	            .claim("provider", provider)    
	            .claim("email", email)
	            .setSubject("TEMP_REGISTER_TOKEN") //아직 회원아니니까 주체는 일반 문자열로 채우겠다
	            .setIssuedAt(now)
	            .setExpiration(new Date(now.getTime() + TEMP_TOKEN_VALID_TIME))
	            .signWith(key, SignatureAlgorithm.HS256)
	            .compact();
	}
	
	public Claims getClaimsFromToken(String token) {
        return Jwts.parserBuilder()
                .setSigningKey(key)
                .build()
                .parseClaimsJws(token)
                .getBody();
    }
	public String createAccessToken(String userPk, String role) {
		 /*권한 배열 말고 일단 계츨구조로  List<String> roles */
        return createToken(userPk, role, ACCESS_TOKEN_VALID_MS, "access");
    }

    public String createRefreshToken(String userPk, String role) {
        return createToken(userPk, role, REFRESH_TOKEN_VALID_MS, "refresh"); 
    }
    
    
    
    public String getUIdFromToken(String token) {
       
        return Jwts.parserBuilder()
                .setSigningKey(key)
                .build()
                .parseClaimsJws(token)//검증 완
                .getBody()
                .getSubject();//uid 꺼내기
    }
    
    public String resolveToken(HttpServletRequest request) {
        
    	String bearerToken = request.getHeader("Authorization");
    	if (bearerToken != null && bearerToken.startsWith("Bearer ")) {
            return bearerToken.substring(7);
        }
        return null;
    }
    
    public boolean validateToken(String token) {
        log.info("[validateToken] 토큰 유효 체크 시작");
        // parseClaimsJws 메서드가 에러 없이 실행되면 유효한 토큰임
        Jwts.parserBuilder() 
        .setSigningKey(key) //비밀키를 검증기(Parser)에 넣어주는 단계
        .build()//검증기 생성(파서)
        .parseClaimsJws(token); //파싱 ( 토큰 분해) + 해싱+검증  or ExpiredJwtException
        return true;
        
    }
    
    
    
    public long getRemainingTtlSeconds(String token) {
        try {
           
            Claims claims = Jwts.parserBuilder()
                    .setSigningKey(secretKey)
                    .build()
                    .parseClaimsJws(token)
                    .getBody();

            Date expiration = claims.getExpiration();   
            Date now = new Date();
            long remainingMillis = expiration.getTime() - now.getTime();
            long remainingSeconds = remainingMillis / 1000;
            return Math.max(0, remainingSeconds);

        } catch (Exception e) {
            log.warn("토큰 TTL 계산 실패: {}", e.getMessage());
            return 0;
        }
    }
    
    
    public String getUidFromExpiredToken(String token) {
        try {
           
            return Jwts.parserBuilder()
                    .setSigningKey(key)
                    .build()
                    .parseClaimsJws(token)
                    .getBody()
                    .getSubject(); 
        } catch (ExpiredJwtException e) {
           
            return e.getClaims().getSubject(); 
        }
    }
}
