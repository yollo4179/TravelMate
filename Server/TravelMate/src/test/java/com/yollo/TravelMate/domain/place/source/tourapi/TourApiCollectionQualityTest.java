package com.yollo.TravelMate.domain.place.source.tourapi;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withServerError;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.place.source.tourapi.client.TourApiPlaceListClient;
import com.yollo.TravelMate.domain.place.source.tourapi.client.TourApiUrlBuilder;
import com.yollo.TravelMate.domain.place.source.tourapi.client.TourApiResponseClient;

class TourApiCollectionQualityTest {

    private static final String TEST_URL = "https://example.invalid/places";
    private MockRestServiceServer server;
    private TourApiPlaceListClient listClient;

    @BeforeEach
    void setUp() {
        RestClient.Builder builder = RestClient.builder();
        server = MockRestServiceServer.bindTo(builder).build();
        TourApiUrlBuilder urlBuilder = mock(TourApiUrlBuilder.class);
        when(urlBuilder.areaBasedList("1", "12", 100, 2)).thenReturn(TEST_URL);
        listClient = new TourApiPlaceListClient(new TourApiResponseClient(new ObjectMapper(), builder), urlBuilder);
    }

    @Test
    void legitimateEmptyResponseRemainsAnEmptyResult() {
        server.expect(requestTo(TEST_URL)).andRespond(withSuccess(
                "{\"response\":{\"header\":{\"resultCode\":\"0000\"},\"body\":{\"totalCount\":0,\"items\":{}}}}",
                MediaType.APPLICATION_JSON
        ));
        assertEquals(0, listClient.fetchPage("1", "12", 100, 2).totalCount());
        server.verify();
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "{\"response\":{\"header\":{\"resultCode\":\"quota_exceeded\"}}}",
            "{\"response\":{\"body\":{\"totalCount\":200,\"items\":{}}}}",
            "{\"response\":{\"body\":{\"totalCount\":\"not-a-count\",\"items\":{}}}}",
            "{\"response\":{\"body\":{\"totalCount\":-1,\"items\":{}}}}",
            "{\"response\":{\"body\":{\"totalCount\":1,\"items\":{\"item\":{\"title\":\"missing-id\"}}}}}",
            "not-json"
    })
    void invalidResponsesCannotMasqueradeAsFinishedCollection(String response) {
        server.expect(requestTo(TEST_URL)).andRespond(withSuccess(response, MediaType.APPLICATION_JSON));
        assertThrows(IllegalStateException.class, () -> listClient.fetchPage("1", "12", 100, 2));
        server.verify();
    }

    @Test
    void httpFailureStopsTheCurrentPage() {
        server.expect(requestTo(TEST_URL)).andRespond(withServerError());
        assertThrows(IllegalStateException.class, () -> listClient.fetchPage("1", "12", 100, 2));
        server.verify();
    }
}
