package com.yollo.TravelMate.exceptions.errorCodes;

import lombok.Builder;
import lombok.Getter;

@Getter
public class ErrorResponse {

	private final int status ; 
	private final String code; 
	private final String message ;
	
	
	@Builder
	public ErrorResponse(int status , String code, String message) {
		this.status = status ; 
		this.code = code; 
		this.message= message;
	}
	
}
