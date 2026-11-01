package com.yollo.TravelMate.domain.plan.validator;

import com.yollo.TravelMate.domain.place.data.result.PlaceResult;
import com.yollo.TravelMate.domain.plan.data.request.PlanContext;

public final class PlanAreaValidator {
    private PlanAreaValidator() {}

    public static boolean contains(PlanContext.Area area, PlaceResult place) {
        return distanceMeters(area.center(), place) <= area.radiusMeters();
    }

    private static double distanceMeters(PlanContext.Coordinate center, PlaceResult place) {
        if (place.latitude() == null || place.longitude() == null
                || !Double.isFinite(place.latitude()) || !Double.isFinite(place.longitude())
                || Math.abs(place.latitude()) > 90 || Math.abs(place.longitude()) > 180) {
            return Double.POSITIVE_INFINITY;
        }
        double latitudeDelta = Math.toRadians(place.latitude() - center.lat());
        double longitudeDelta = Math.toRadians(place.longitude() - center.lon());
        double haversine = Math.pow(Math.sin(latitudeDelta / 2), 2)
                + Math.cos(Math.toRadians(center.lat())) * Math.cos(Math.toRadians(place.latitude()))
                * Math.pow(Math.sin(longitudeDelta / 2), 2);
        return 6371000 * 2 * Math.asin(Math.sqrt(Math.min(1, haversine)));
    }
}
