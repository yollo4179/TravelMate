package com.yollo.TravelMate.domain.place.data.result;



public record PlaceResult (
		 Long id, 
		 String name,
		 String description, 
		 String region,
		 String category,
		 Double latitude, 
		 Double longitude,
		 Double similarity	
){}


