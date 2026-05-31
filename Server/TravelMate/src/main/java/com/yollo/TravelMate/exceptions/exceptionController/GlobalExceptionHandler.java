package com.yollo.TravelMate.exceptions.exceptionController;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import com.yollo.TravelMate.exceptions.cumtom.ErrorCodeException;
import com.yollo.TravelMate.exceptions.errorCodes.ErrorCode;
import com.yollo.TravelMate.exceptions.errorCodes.ErrorResponse;

import io.jsonwebtoken.ExpiredJwtException;
import io.jsonwebtoken.JwtException;

@RestControllerAdvice
public class GlobalExceptionHandler {

	/************제공에러 핸들링***************/
	/*액세스 토큰 만료*/
	@ExceptionHandler(ExpiredJwtException.class)
    public ResponseEntity<ErrorResponse> handleExpiredJwtException(ExpiredJwtException e) {
        ErrorCode errorCode = ErrorCode.ERR_TOKEN_EXPIRED; 
        return createErrorResponse(errorCode);
    }
	
	
	/*jwt 위조 */
	@ExceptionHandler(JwtException.class)
    public ResponseEntity<ErrorResponse> handleJwtException(JwtException e) {
        ErrorCode errorCode = ErrorCode.ERR_TOKEN_INVALID;
        return createErrorResponse(errorCode);
    }

	/* 이상한 인자 전달 시 호출 */
	@ExceptionHandler(IllegalArgumentException.class)
	public ResponseEntity<ErrorResponse> handleIllegalArgumentException(IllegalArgumentException e) {
		ErrorResponse response = ErrorResponse.builder()
				.status(400)
				.code("ERR_BAD_REQUEST")
				.message(e.getMessage())
				.build();
		return ResponseEntity.badRequest().body(response);
	}
	/************제공에러 핸들링***************/
	
	/************커스텀 에러******************/
	@ExceptionHandler(ErrorCodeException.class)
    public ResponseEntity<ErrorResponse> handleErrorResponseException(ErrorCodeException e){
        return createErrorResponse(e.getErrorCode());
    }
	/************커스텀 에러******************/
	
	
	private ResponseEntity<ErrorResponse> createErrorResponse(ErrorCode errorCode) {
        ErrorResponse response = ErrorResponse.builder()
                .status(errorCode.getHttpStatus().value())
                .code(errorCode.getCode())
                .message(errorCode.getMessage())
                .build();
        return new ResponseEntity<>(response, errorCode.getHttpStatus());
    }
	
	
	
	
	@ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ErrorResponse> handleValidationException(MethodArgumentNotValidException e) {
        String defaultMessage = e.getBindingResult().getFieldError().getDefaultMessage();
        
        ErrorResponse response = ErrorResponse.builder()
                .status(400)
                .code("ERR_BAD_REQUEST")
                .message(defaultMessage)
                .build();
                
        return ResponseEntity.badRequest().body(response);
    }
}
