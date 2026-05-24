package com.yollo.TravelMate.redis;

import java.util.concurrent.TimeUnit;

import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.stereotype.Service;

import lombok.RequiredArgsConstructor;

@Service
@RequiredArgsConstructor
public class RedisService {

	final private RedisTemplate<String, Object>redisTemplate;
	
	//로그인 시 호출
	public void saveRefreshToken(String uid, String token, long ttlSeconds) {
        
        redisTemplate.opsForValue().set(
        		RedisKeyType.REFRESH_TOKEN.make(uid),
            token, 
            ttlSeconds, 
            TimeUnit.SECONDS
        );
    }

	
	
	/*액세스 만료로 Refresh 요청 시 refresh 검증용*/
    public String getRefreshToken(String uid) {
        
        return (String) redisTemplate.opsForValue().get(RedisKeyType.REFRESH_TOKEN.make(uid));
    }
    /*로그아웃 시 호출 */
    public void logout(String uid, String accessToken, long remainingTtlSeconds) {
    	String refreshKey = RedisKeyType.REFRESH_TOKEN.make(uid);
        redisTemplate.delete(refreshKey);
    	
    	String blackListKey =RedisKeyType.BLACKLIST.make(accessToken);
        redisTemplate.opsForValue().set(
        		blackListKey,
        		"logout",
        		remainingTtlSeconds,
        		TimeUnit.SECONDS);
    }

    /* API 요청이 올 때마다 필터에서 호출*/
    public boolean isBlacklisted(String accessToken) {
        String key = RedisKeyType.BLACKLIST.make(accessToken);
        return Boolean.TRUE.equals(redisTemplate.hasKey(key));
    }

}
