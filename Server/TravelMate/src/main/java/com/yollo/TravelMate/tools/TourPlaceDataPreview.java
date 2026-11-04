package com.yollo.TravelMate.tools;

import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.place.source.tourapi.client.TourApiPlaceDetailClient;
import com.yollo.TravelMate.domain.place.source.tourapi.client.TourApiPlaceListClient;
import com.yollo.TravelMate.domain.place.source.tourapi.code.TourContentType;
import com.yollo.TravelMate.domain.place.source.tourapi.code.TourCoordinateStatus;
import com.yollo.TravelMate.domain.place.source.tourapi.data.TourPlaceCandidate;
import com.yollo.TravelMate.domain.place.source.tourapi.mapper.TourPlaceCoordinateValidator;
import com.yollo.TravelMate.domain.place.source.tourapi.mapper.TourPlaceDescriptionBuilder;

import lombok.Builder;

public final class TourPlaceDataPreview {

    public enum PreviewStatus {
        OFFLINE_PREVIEW_ONLY
    }

    private TourPlaceDataPreview() {
    }

    public static void main(String[] arguments) throws Exception {
        if (arguments.length != 2) {
            throw new IllegalArgumentException("snapshotPath와 previewOutput을 지정해야 합니다.");
        }
        Path snapshotPath = Path.of(arguments[0]).toAbsolutePath().normalize();
        Path outputPath = Path.of(arguments[1]).toAbsolutePath().normalize();
        if (Files.exists(outputPath)) {
            throw new IllegalArgumentException("기존 검토 결과를 덮어쓰지 않습니다: " + outputPath);
        }
        ObjectMapper objectMapper = new ObjectMapper();
        byte[] snapshotBytes = Files.readAllBytes(snapshotPath);
        JsonNode snapshot = objectMapper.readTree(snapshotBytes);
        Map<String, JsonNode> rawByContentId = new HashMap<>();
        snapshot.path("tour_api_raw").forEach(raw -> rawByContentId.put(raw.path("tour_content_id").asText(), raw));
        TourPlaceDescriptionBuilder descriptionBuilder = new TourPlaceDescriptionBuilder();
        TourPlaceCoordinateValidator coordinateValidator = new TourPlaceCoordinateValidator();
        List<PlacePreview> places = new ArrayList<>();
        for (JsonNode place : snapshot.path("places")) {
            String contentId = place.path("tour_content_id").asText();
            JsonNode raw = rawByContentId.get(contentId);
            if (raw == null) {
                throw new IllegalArgumentException("원본이 없는 장소: " + contentId);
            }
            var item = TourApiPlaceListClient.toListItem(raw.path("raw_list"));
            var common = TourApiPlaceDetailClient.toCommonResult(raw.path("raw_common"));
            var informationItems = TourApiPlaceDetailClient.toInfoResult(raw.path("raw_info")).items();
            TourContentType contentType = TourContentType.fromContentTypeId(raw.path("tour_content_type_id").asText());
            if (contentType == null) {
                throw new IllegalArgumentException("지원하지 않는 콘텐츠 유형: " + contentId);
            }
            String description = descriptionBuilder.build(
                    contentType,
                    place.path("source_category").asText(null),
                    common.overview(),
                    informationItems
            );
            var candidate = new TourPlaceCandidate(
                    item,
                    common,
                    place.path("region").asText(null),
                    place.path("city").asText(null),
                    contentType,
                    place.path("source_category").asText(null),
                    description,
                    informationItems
            );
            places.add(PlacePreview.builder()
                    .placeId(place.path("id").asLong())
                    .tourContentId(item.contentId())
                    .name(item.title())
                    .coordinateStatus(coordinateValidator.validate(item.mapY(), item.mapX()))
                    .hasSearchableContent(candidate.hasSearchableContent())
                    .supplementalFieldCount(informationItems.stream()
                            .filter(TourApiPlaceDetailClient.TourApiInfoItem::hasContent)
                            .count())
                    .currentDescription(place.path("description").asText())
                    .proposedDescription(description)
                    .build());
        }
        var report = PreviewReport.builder()
                .status(PreviewStatus.OFFLINE_PREVIEW_ONLY)
                .snapshotSha256(HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(snapshotBytes)))
                .placeCount(places.size())
                .validCoordinateCount(places.stream()
                        .filter(place -> place.coordinateStatus() == TourCoordinateStatus.VALID)
                        .count())
                .coordinateReviewCount(places.stream()
                        .filter(place -> place.coordinateStatus() != TourCoordinateStatus.VALID)
                        .count())
                .changedDescriptionCount(places.stream()
                        .filter(place -> !place.currentDescription().equals(place.proposedDescription()))
                        .count())
                .databaseModified(false)
                .externalApiCalled(false)
                .places(places)
                .build();
        Files.createDirectories(outputPath.getParent());
        objectMapper.writerWithDefaultPrettyPrinter().writeValue(outputPath.toFile(), report);
        System.out.printf("미리보기 완료: 전체=%d, 유효좌표=%d, 좌표확인대기=%d, 설명변경=%d%n",
                report.placeCount(), report.validCoordinateCount(), report.coordinateReviewCount(), report.changedDescriptionCount());
    }

    @Builder
    public record PlacePreview(
            long placeId,
            String tourContentId,
            String name,
            TourCoordinateStatus coordinateStatus,
            boolean hasSearchableContent,
            long supplementalFieldCount,
            String currentDescription,
            String proposedDescription
    ) {
    }

    @Builder
    public record PreviewReport(
            PreviewStatus status,
            String snapshotSha256,
            int placeCount,
            long validCoordinateCount,
            long coordinateReviewCount,
            long changedDescriptionCount,
            boolean databaseModified,
            boolean externalApiCalled,
            List<PlacePreview> places
    ) {
    }
}
