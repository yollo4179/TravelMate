package com.yollo.TravelMate.domain.place.data.entity;

import java.time.LocalDateTime;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.Getter;


@Entity
@Table(name = "places")
@Getter
public class Place {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    private String name;

    private String description;

    private String region;
    
    private String city;

    private String category;

    private String sourceCategory;
    
    private Double latitude;

    private Double longitude;

    private String kakaoPlaceId;


    private LocalDateTime createdAt;
}