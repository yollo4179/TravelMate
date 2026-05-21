package com.yollo.TravelMate.jwt.Filters;

import java.io.IOException;

import org.springframework.web.filter.OncePerRequestFilter;
import org.springframework.web.servlet.HandlerExceptionResolver;

import io.jsonwebtoken.ExpiredJwtException;
import io.jsonwebtoken.JwtException;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

public class JwtExceptionFilter extends OncePerRequestFilter{

	private final HandlerExceptionResolver resolver;
	public JwtExceptionFilter(HandlerExceptionResolver resolver) {
        this.resolver = resolver;
    }
	@Override
	protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain filterChain)
			throws ServletException, IOException {
		try {
            filterChain.doFilter(request, response);
        }
		catch (ExpiredJwtException e) {
			resolver.resolveException(request, response, null, e); 
		}
		catch (JwtException | IllegalArgumentException e) {
            resolver.resolveException(request, response, null, e);
        }
	}
	
	
}
