package com.yollo.TravelMate;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import org.springframework.data.jpa.repository.config.EnableJpaAuditing;

@EnableJpaAuditing
@SpringBootApplication
public class TravelMateApplication {

	public static void main(String[] args) {
		SpringApplication.run(TravelMateApplication.class, args);
	}

}
