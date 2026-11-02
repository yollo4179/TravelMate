package com.yollo.TravelMate.domain.place.source.tourapi.client;

import java.util.List;
import java.util.stream.StreamSupport;

import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestClientResponseException;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.place.source.tourapi.code.TourApiFailureReason;

@Component
public final class TourApiResponseClient {

    private static final String SUCCESS_CODE = "0000";

    private final RestClient restClient;
    private final ObjectMapper objectMapper;

    public TourApiResponseClient(
            ObjectMapper objectMapper,
            RestClient.Builder restClientBuilder
    ) {
        this.objectMapper = objectMapper;
        this.restClient = restClientBuilder.clone().build();
    }

    public ResponsePage fetch(String url) {
        String rawResponse;
        try {
            rawResponse = restClient.get().uri(url).retrieve().body(String.class);
        } catch (RestClientResponseException exception) {
            throw TourApiCollectionException.builder()
                    .reason(TourApiFailureReason.HTTP_ERROR)
                    .rawResponse(exception.getResponseBodyAsString())
                    .cause(exception)
                    .build();
        } catch (RestClientException exception) {
            throw TourApiCollectionException.builder()
                    .reason(TourApiFailureReason.TRANSPORT_ERROR)
                    .cause(exception)
                    .build();
        }
        return parse(rawResponse);
    }

    private ResponsePage parse(String rawResponse) {
        if (rawResponse == null || rawResponse.isBlank()) {
            throw failure(TourApiFailureReason.INVALID_RESPONSE, rawResponse);
        }
        JsonNode root;
        try {
            root = objectMapper.reader()
                    .with(DeserializationFeature.FAIL_ON_TRAILING_TOKENS)
                    .readTree(rawResponse);
        } catch (JsonProcessingException exception) {
            throw TourApiCollectionException.builder()
                    .reason(TourApiFailureReason.INVALID_RESPONSE)
                    .rawResponse(rawResponse)
                    .cause(exception)
                    .build();
        }
        JsonNode response = root.path("response");
        JsonNode code = response.path("header").path("resultCode");
        if (!code.isTextual() || code.asText().isBlank()) {
            throw failure(TourApiFailureReason.INVALID_RESPONSE, rawResponse);
        }
        if (!SUCCESS_CODE.equals(code.asText())) {
            throw failure(TourApiFailureReason.PROVIDER_ERROR, rawResponse);
        }
        JsonNode body = response.path("body");
        JsonNode count = body.path("totalCount");
        if (!body.isObject() || !count.isValueNode() || !count.asText().matches("[0-9]+")) {
            throw failure(TourApiFailureReason.INVALID_RESPONSE, rawResponse);
        }
        int totalCount;
        try {
            totalCount = Integer.parseInt(count.asText());
        } catch (NumberFormatException exception) {
            throw failure(TourApiFailureReason.INVALID_RESPONSE, rawResponse);
        }
        JsonNode items = body.path("items");
        if (!items.isObject() && !(items.isTextual() && items.asText().isBlank())) {
            throw failure(TourApiFailureReason.INVALID_RESPONSE, rawResponse);
        }
        JsonNode item = items.path("item");
        List<JsonNode> records = parseItems(item, rawResponse);
        if ((totalCount == 0 && !records.isEmpty()) || (totalCount > 0 && records.isEmpty())
                || records.size() > totalCount) {
            throw failure(TourApiFailureReason.INCONSISTENT_PAGE, rawResponse);
        }
        return new ResponsePage(totalCount, records, rawResponse);
    }

    private List<JsonNode> parseItems(
            JsonNode item,
            String rawResponse
    ) {
        if (item.isArray()) {
            List<JsonNode> records = StreamSupport.stream(item.spliterator(), false).toList();
            if (records.stream().anyMatch(record -> !record.isObject() || record.isEmpty())) {
                throw failure(TourApiFailureReason.INVALID_RESPONSE, rawResponse);
            }
            return records;
        }
        if (item.isObject() && !item.isEmpty()) {
            return List.of(item);
        }
        if (item.isMissingNode() || item.isNull() || (item.isTextual() && item.asText().isBlank())) {
            return List.of();
        }
        throw failure(TourApiFailureReason.INVALID_RESPONSE, rawResponse);
    }

    private TourApiCollectionException failure(
            TourApiFailureReason reason,
            String rawResponse
    ) {
        return TourApiCollectionException.builder().reason(reason).rawResponse(rawResponse).build();
    }

    public record ResponsePage(
            int totalCount,
            List<JsonNode> items,
            String rawResponse
    ) {
        public ResponsePage {
            items = List.copyOf(items);
        }
    }
}
