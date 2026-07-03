package com.yollo.TravelMate.exceptions.errorCodes;

import org.springframework.http.HttpStatus;

import lombok.Getter;

@Getter
public enum ErrorCode {

	/**********ENUM CODE*************/
	ERR_TOKEN_EXPIRED(HttpStatus.UNAUTHORIZED, "ERR_TOKEN_EXPIRED", "Access token has expired. Please refresh."),
	ERR_ACCESS_TOKEN_EXPIRED(HttpStatus.UNAUTHORIZED, "ERR_ACCESS_TOKEN_EXPIRED", "Access token has expired. Please refresh."),
	ERR_REFRESH_TOKEN_EXPIRED(HttpStatus.UNAUTHORIZED, "ERR_REFRESH_TOKEN_EXPIRED", "Refresh token has expired. Please login again."),
	ERR_TEMP_TOKEN_EXPIRED(HttpStatus.UNAUTHORIZED, "ERR_TEMP_TOKEN_EXPIRED", "Signup time has expired. Please try again."),
    ERR_TOKEN_INVALID(HttpStatus.UNAUTHORIZED, "ERR_TOKEN_INVALID", "Invalid or tampered access token."),

    DUPLICATED_USER_ID(HttpStatus.CONFLICT, "ERR_USER_001", "이미 존재하는 아이디입니다."),
    DUPLICATED_NICKNAME(HttpStatus.CONFLICT, "ERR_USER_002", "이미 존재하는 닉네임입니다."),
    USER_NOT_FOUND(HttpStatus.NOT_FOUND, "ERR_USER_003", "존재하지 않는 사용자입니다."),
	USER_INVALID(HttpStatus.UNAUTHORIZED, "ERR_USER_INVALID" , "리프레시 토큰이 일치하지 않습니다."),
	
	
	ROOM_NOT_FOUND(HttpStatus.NOT_FOUND, "ERR_ROOM_001", "존재하지 않는 방입니다."),
	INVALID_ROOM_PASSWORD(HttpStatus.BAD_REQUEST, "ERR_ROOM_002", "비밀번호가 일치하지 않습니다."),
	ROOM_MEMBER_NOT_FOUND(HttpStatus.NOT_FOUND, "ERR_ROOM_003", "방에 참여하고 있지 않은 사용자입니다."),
	
	
	/**********PLAN / AI*************/
	PLAN_NO_CANDIDATES(HttpStatus.NOT_FOUND, "ERR_PLAN_001", "검색 결과가 없어 플랜을 생성할 수 없습니다."),
	PLAN_LLM_PARSE_FAILED(HttpStatus.UNPROCESSABLE_ENTITY, "ERR_PLAN_002", "AI 응답을 해석할 수 없습니다. 다시 시도해주세요."),
	PLAN_EMPTY_PINS(HttpStatus.UNPROCESSABLE_ENTITY, "ERR_PLAN_003", "생성된 플랜에 장소가 없습니다."),
	PLAN_ALL_HALLUCINATED(HttpStatus.UNPROCESSABLE_ENTITY, "ERR_PLAN_004", "유효한 장소를 찾지 못했습니다. 다시 시도해주세요."),
	LLM_SERVER_UNAVAILABLE(HttpStatus.SERVICE_UNAVAILABLE, "ERR_AI_001", "AI 서버에 연결할 수 없습니다."),
	EMBEDDING_SERVER_UNAVAILABLE(HttpStatus.SERVICE_UNAVAILABLE, "ERR_AI_002", "임베딩 서버에 연결할 수 없습니다.");
	/**********PLAN / AI*************/
	
	
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
