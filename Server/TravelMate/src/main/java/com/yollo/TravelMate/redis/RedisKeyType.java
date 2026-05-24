package com.yollo.TravelMate.redis;


public enum RedisKeyType {

	
	REFRESH_TOKEN("travel_mate:auth:refresh:"),
	BLACKLIST("travel_mate:auth:blacklist:");
	
	private final String keyName ; 
	
	RedisKeyType(String keyName){
		this.keyName = keyName;
	}
	public String make(Object identifier) { 
        return this.keyName + identifier.toString();
    }
	/*도메인 + 객체 식별자*/
	
}
