package com.yollo.TravelMate.domain.place.repository;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import com.yollo.TravelMate.domain.place.data.entity.Place;

@Repository
public interface PlaceJpaRepository 
	extends JpaRepository<Place, Long> {


	

	
}
