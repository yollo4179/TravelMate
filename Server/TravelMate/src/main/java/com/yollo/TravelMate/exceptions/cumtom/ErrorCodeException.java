package com.yollo.TravelMate.exceptions.cumtom;

import com.yollo.TravelMate.exceptions.errorCodes.ErrorCode;

import lombok.Getter;

@Getter
public class ErrorCodeException extends RuntimeException{

	
	private final ErrorCode errorCode ; 
	
	public ErrorCodeException(ErrorCode errorCode) {
		super(errorCode.getMessage());
		this.errorCode = errorCode;
	}
}
