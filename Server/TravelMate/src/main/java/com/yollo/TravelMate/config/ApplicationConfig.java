package com.yollo.TravelMate.config;
import java.sql.Driver;

import javax.sql.DataSource;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.datasource.SimpleDriverDataSource;

@Configuration
public class ApplicationConfig {
	 @SuppressWarnings("unchecked")
		
	    @Bean
	    public DataSource dataSource() {
	    	//SimpleDriverDataSource 이란
	        //스프링에서 connection을 관리해주는 클래스, connection을 관리한다.  
	    	SimpleDriverDataSource ds = new SimpleDriverDataSource();
	        try {
				ds.setDriverClass((Class<Driver>) Class.forName("org.postgresql.Driver"));
			} catch (ClassNotFoundException e) {
				e.printStackTrace();
			}
	        ds.setUrl("jdbc:postgresql://127.0.0.1:5432/TravelMate?serverTimezone=Asia/Seoul&useUniCode=yes&characterEncoding=UTF-8");
	        ds.setUsername("ssafy");
	        ds.setPassword("ssafy");
	        return ds;
	    }
}




