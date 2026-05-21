package com.yollo.TravelMate.exceptions.errorCodes;

import org.springframework.http.HttpStatus;

import lombok.Getter;

@Getter
public enum ErrorCode {

	/**********ENUM CODE*************/
	ERR_TOKEN_EXPIRED(HttpStatus.UNAUTHORIZED, "ERR_TOKEN_EXPIRED", "Access token has expired. Please refresh."),
    ERR_TOKEN_INVALID(HttpStatus.UNAUTHORIZED, "ERR_TOKEN_INVALID", "Invalid or tampered access token."),

    DUPLICATED_USER_ID(HttpStatus.CONFLICT, "ERR_USER_001", "이미 존재하는 아이디입니다."),
    DUPLICATED_NICKNAME(HttpStatus.CONFLICT, "ERR_USER_002", "이미 존재하는 닉네임입니다."),
    USER_NOT_FOUND(HttpStatus.NOT_FOUND, "ERR_USER_003", "존재하지 않는 사용자입니다.");
	/**********ENUM CODE*************/
	
	
	private final HttpStatus httpStatus;
    private final String code;
    private final String message;

    ErrorCode(HttpStatus httpStatus, String code, String message) {
        this.httpStatus = httpStatus;
        this.code = code;
        this.message = message;
    }
	
}
