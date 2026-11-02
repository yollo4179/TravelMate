package com.yollo.TravelMate.domain.place.source.tourapi;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.verifyNoMoreInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withException;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withServerError;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

import java.io.IOException;
import java.util.List;
import java.util.function.Supplier;
import java.util.stream.IntStream;
import java.util.stream.Stream;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.EnumSource;
import org.junit.jupiter.params.provider.MethodSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.place.repository.PlaceCatalogRepository;
import com.yollo.TravelMate.domain.place.repository.PlaceDetailRepository;
import com.yollo.TravelMate.domain.place.source.tourapi.client.TourApiCollectionException;
import com.yollo.TravelMate.domain.place.source.tourapi.client.TourApiPlaceDetailClient;
import com.yollo.TravelMate.domain.place.source.tourapi.client.TourApiPlaceListClient;
import com.yollo.TravelMate.domain.place.source.tourapi.client.TourApiResponseClient;
import com.yollo.TravelMate.domain.place.source.tourapi.client.TourApiUrlBuilder;
import com.yollo.TravelMate.domain.place.source.tourapi.code.TourApiFailureReason;
import com.yollo.TravelMate.domain.place.source.tourapi.code.TourAreaCode;
import com.yollo.TravelMate.domain.place.source.tourapi.code.TourContentType;
import com.yollo.TravelMate.domain.place.source.tourapi.repository.TourPlaceRawRepository;
import com.yollo.TravelMate.domain.place.source.tourapi.service.TourPlaceDetailSyncService;
import com.yollo.TravelMate.domain.place.source.tourapi.service.TourPlaceRawCollectionService;

class TourApiFailurePreservationTest {

    private static final String TEST_URL = "https://example.invalid/tourapi";
    private static final ObjectMapper JSON = new ObjectMapper();
    private MockRestServiceServer server;
    private TourApiPlaceListClient listClient;
    private TourApiPlaceDetailClient detailClient;

    enum Endpoint { LIST, COMMON, INTRO, INFO }

    @BeforeEach
    void setUp() {
        RestClient.Builder builder = RestClient.builder();
        server = MockRestServiceServer.bindTo(builder).build();
        TourApiUrlBuilder urls = mock(TourApiUrlBuilder.class);
        when(urls.areaBasedList(anyString(), anyString(), anyInt(), anyInt())).thenReturn(TEST_URL);
        when(urls.detailCommon(anyString())).thenReturn(TEST_URL);
        when(urls.detail(anyString(), anyString(), anyString(), anyInt())).thenReturn(TEST_URL);
        when(urls.detail(anyString(), anyString(), anyString(), anyInt(), anyInt())).thenReturn(TEST_URL);
        var responses = new TourApiResponseClient(JSON, builder);
        listClient = new TourApiPlaceListClient(responses, urls);
        detailClient = new TourApiPlaceDetailClient(responses, JSON, urls);
    }

    private Supplier<?> request(Endpoint endpoint) {
        return switch (endpoint) {
            case LIST -> () -> listClient.fetchPage("1", "12", 100, 1);
            case COMMON -> () -> detailClient.fetchCommon("preserved");
            case INTRO -> () -> detailClient.fetchIntro("preserved", "12");
            case INFO -> () -> detailClient.fetchInfoItems("preserved", "12");
        };
    }

    private static String response(
            int totalCount,
            String items
    ) {
        return "{\"response\":{\"header\":{\"resultCode\":\"0000\"},\"body\":{\"totalCount\":"
                + totalCount + ",\"items\":" + items + "}}}";
    }

    static Stream<Arguments> failures() {
        return Stream.of(
                Arguments.of("", TourApiFailureReason.INVALID_RESPONSE),
                Arguments.of("null", TourApiFailureReason.INVALID_RESPONSE),
                Arguments.of("not-json", TourApiFailureReason.INVALID_RESPONSE),
                Arguments.of("<OpenAPI_ServiceResponse>quota</OpenAPI_ServiceResponse>", TourApiFailureReason.INVALID_RESPONSE),
                Arguments.of("{}", TourApiFailureReason.INVALID_RESPONSE),
                Arguments.of("{\"response\":{\"header\":{\"resultCode\":\"22\"}}}", TourApiFailureReason.PROVIDER_ERROR),
                Arguments.of(response(0, "{}") + " {}", TourApiFailureReason.INVALID_RESPONSE),
                Arguments.of(response(-1, "{}"), TourApiFailureReason.INVALID_RESPONSE),
                Arguments.of(response(0, "{}").replace("\"totalCount\":0", "\"totalCount\":\"bad\""), TourApiFailureReason.INVALID_RESPONSE),
                Arguments.of(response(0, "{}").replace("\"totalCount\":0", "\"totalCount\":2147483648"), TourApiFailureReason.INVALID_RESPONSE),
                Arguments.of(response(0, "null"), TourApiFailureReason.INVALID_RESPONSE),
                Arguments.of(response(1, "{}"), TourApiFailureReason.INCONSISTENT_PAGE),
                Arguments.of(response(0, "{\"item\":{\"contentid\":\"unexpected\"}}"), TourApiFailureReason.INCONSISTENT_PAGE),
                Arguments.of(response(1, "{\"item\":[{}]}"), TourApiFailureReason.INVALID_RESPONSE),
                Arguments.of(response(1, "{\"item\":[null]}"), TourApiFailureReason.INVALID_RESPONSE),
                Arguments.of(response(1, "{\"item\":[1]}"), TourApiFailureReason.INVALID_RESPONSE)
        ).flatMap(arguments -> Stream.of(Endpoint.values()).map(endpoint -> Arguments.of(
                endpoint, arguments.get()[0], arguments.get()[1]
        )));
    }

    @ParameterizedTest
    @MethodSource("failures")
    void failuresRetainTheirResponseAndReasonAcrossEveryEndpoint(
            Endpoint endpoint,
            String rawResponse,
            TourApiFailureReason reason
    ) {
        server.expect(requestTo(TEST_URL)).andRespond(withSuccess(rawResponse, MediaType.APPLICATION_JSON));
        var failure = assertThrows(TourApiCollectionException.class, () -> request(endpoint).get());
        assertEquals(reason, failure.getReason());
        assertEquals(rawResponse.isEmpty() ? null : rawResponse, failure.getRawResponse());
        server.verify();
    }

    @ParameterizedTest
    @EnumSource(Endpoint.class)
    void httpErrorsAreNeverReturnedAsEmptyValues(Endpoint endpoint) {
        String originalError = "provider unavailable";
        server.expect(requestTo(TEST_URL)).andRespond(withServerError().body(originalError));
        var failure = assertThrows(TourApiCollectionException.class, () -> request(endpoint).get());
        assertEquals(TourApiFailureReason.HTTP_ERROR, failure.getReason());
        assertEquals(originalError, failure.getRawResponse());
        server.verify();
    }

    @ParameterizedTest
    @EnumSource(Endpoint.class)
    void transportErrorsAreNeverReturnedAsEmptyValues(Endpoint endpoint) {
        server.expect(requestTo(TEST_URL)).andRespond(withException(new IOException("offline timeout")));
        var failure = assertThrows(TourApiCollectionException.class, () -> request(endpoint).get());
        assertEquals(TourApiFailureReason.TRANSPORT_ERROR, failure.getReason());
        assertNull(failure.getRawResponse());
        assertNotNull(failure.getCause());
        server.verify();
    }

    static Stream<Arguments> emptyResponses() {
        return Stream.of("{}", "\"\"", "{\"item\":[]}", "{\"item\":null}")
                .flatMap(items -> Stream.of(Endpoint.values()).map(endpoint -> Arguments.of(endpoint, items)));
    }

    @ParameterizedTest
    @MethodSource("emptyResponses")
    void onlyVerifiedZeroCountsReturnEmptyValues(
            Endpoint endpoint,
            String items
    ) {
        server.expect(requestTo(TEST_URL)).andRespond(withSuccess(response(0, items), MediaType.APPLICATION_JSON));
        Object result = request(endpoint).get();
        switch (endpoint) {
            case LIST -> {
                var page = (TourApiPlaceListClient.TourApiListPage) result;
                assertEquals(0, page.totalCount());
                assertEquals(List.of(), page.items());
            }
            case COMMON -> assertNull(((TourApiPlaceDetailClient.TourApiCommonResult) result).rawJson());
            case INTRO -> assertNull(((TourApiPlaceDetailClient.TourApiIntroResult) result).rawIntroJson());
            case INFO -> {
                var information = (TourApiPlaceDetailClient.TourApiInfoResult) result;
                assertEquals(List.of(), information.items());
                assertNull(information.rawJson());
            }
        }
        server.verify();
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "{\"title\":\"missing id\"}",
            "{\"contentid\":\" \"}",
            "{\"contentid\":\"invalid-coordinate\",\"mapx\":\"not-a-number\"}"
    })
    void malformedListItemsPreserveTheirResponse(String item) {
        String rawResponse = response(1, "{\"item\":" + item + "}");
        server.expect(requestTo(TEST_URL)).andRespond(withSuccess(rawResponse, MediaType.APPLICATION_JSON));
        var failure = assertThrows(TourApiCollectionException.class, () -> request(Endpoint.LIST).get());
        assertEquals(TourApiFailureReason.INVALID_RESPONSE, failure.getReason());
        assertEquals(rawResponse, failure.getRawResponse());
        server.verify();
    }

    @Test
    void truncatedListPagesCannotReportSuccessfulCollection() {
        String rawResponse = response(200, "{\"item\":{\"contentid\":\"partial-page\"}}");
        server.expect(requestTo(TEST_URL)).andRespond(withSuccess(rawResponse, MediaType.APPLICATION_JSON));
        var failure = assertThrows(TourApiCollectionException.class, () -> request(Endpoint.LIST).get());
        assertEquals(TourApiFailureReason.INCONSISTENT_PAGE, failure.getReason());
        assertEquals(rawResponse, failure.getRawResponse());
        server.verify();
    }

    @ParameterizedTest
    @EnumSource(value = Endpoint.class, names = {"COMMON", "INTRO"})
    void singleRecordEndpointsCannotSilentlyDropExtraResults(Endpoint endpoint) {
        String rawResponse = response(2, "{\"item\":[{\"overview\":\"one\"},{\"overview\":\"two\"}]}");
        server.expect(requestTo(TEST_URL)).andRespond(withSuccess(rawResponse, MediaType.APPLICATION_JSON));
        var failure = assertThrows(TourApiCollectionException.class, () -> request(endpoint).get());
        assertEquals(TourApiFailureReason.INCONSISTENT_PAGE, failure.getReason());
        assertEquals(rawResponse, failure.getRawResponse());
        server.verify();
    }

    @Test
    void objectAndArrayItemsBothPreserveOriginalSupplementalFields() throws Exception {
        String item = "{\"infoname\":\"입 장 료\",\"infotext\":\"무료<br>어린이&nbsp;포함\",\"serialnum\":\"0\"}";
        for (String items : List.of(item, "[" + item + "]")) {
            server.expect(requestTo(TEST_URL)).andRespond(withSuccess(
                    response(1, "{\"item\":" + items + "}"),
                    MediaType.APPLICATION_JSON
            ));
        }
        for (int index = 0; index < 2; index++) {
            var result = detailClient.fetchInfoItems("preserved", "12");
            assertEquals("입 장 료", result.items().get(0).infoName());
            assertEquals("무료<br>어린이&nbsp;포함", result.items().get(0).infoText());
            assertEquals(JSON.readTree("[" + item + "]"), JSON.readTree(result.rawJson()));
        }
        server.verify();
    }

    private String fullInfoPage() {
        var items = JSON.createArrayNode();
        IntStream.range(0, 100).mapToObj(index -> JSON.createObjectNode()
                        .put("infoname", "안내")
                        .put("infotext", "보존 본문 " + index)
                        .put("serialnum", Integer.toString(index)))
                .forEach(items::add);
        return response(101, "{\"item\":" + items + "}");
    }

    @Test
    void allInfoPagesAreCollectedBeforeReturning() {
        server.expect(requestTo(TEST_URL)).andRespond(withSuccess(fullInfoPage(), MediaType.APPLICATION_JSON));
        server.expect(requestTo(TEST_URL)).andRespond(withSuccess(
                response(101, "{\"item\":{\"infoname\":\"마지막\",\"infotext\":\"본문\",\"serialnum\":\"100\"}}"),
                MediaType.APPLICATION_JSON
        ));
        assertEquals(101, detailClient.fetchInfoItems("preserved", "12").items().size());
        server.verify();
    }

    @Test
    void laterPageFailureCannotDeletePreviouslySavedPrograms() {
        server.expect(requestTo(TEST_URL)).andRespond(withSuccess(response(0, "{}"), MediaType.APPLICATION_JSON));
        server.expect(requestTo(TEST_URL)).andRespond(withSuccess(fullInfoPage(), MediaType.APPLICATION_JSON));
        server.expect(requestTo(TEST_URL)).andRespond(withServerError().body("page two failed"));
        PlaceDetailRepository repository = mock(PlaceDetailRepository.class);
        var sync = new TourPlaceDetailSyncService(detailClient, repository);
        assertThrows(TourApiCollectionException.class, () -> sync.syncDetail(1L, "preserved", "12"));
        verifyNoInteractions(repository);
        server.verify();
    }

    @Test
    void changedTotalCannotReturnPartialInformation() {
        server.expect(requestTo(TEST_URL)).andRespond(withSuccess(fullInfoPage(), MediaType.APPLICATION_JSON));
        String changedPage = response(0, "{}");
        server.expect(requestTo(TEST_URL)).andRespond(withSuccess(changedPage, MediaType.APPLICATION_JSON));
        var failure = assertThrows(TourApiCollectionException.class, () -> detailClient.fetchInfoItems("preserved", "12"));
        assertEquals(TourApiFailureReason.INCONSISTENT_PAGE, failure.getReason());
        assertEquals(changedPage, failure.getRawResponse());
        server.verify();
    }

    @Test
    void detailFailureCannotSaveMissingContentAsSuccessfulRawCollection() {
        server.expect(requestTo(TEST_URL)).andRespond(withSuccess(
                response(1, "{\"item\":{\"contentid\":\"preserved\",\"contenttypeid\":\"12\"}}"),
                MediaType.APPLICATION_JSON
        ));
        server.expect(requestTo(TEST_URL)).andRespond(withServerError());
        var catalog = mock(PlaceCatalogRepository.class);
        var raw = mock(TourPlaceRawRepository.class);
        var collector = new TourPlaceRawCollectionService(listClient, detailClient, catalog, raw);
        assertThrows(TourApiCollectionException.class, () -> collector.collectRaw(
                List.of(TourAreaCode.서울),
                List.of(TourContentType.관광지)
        ));
        verify(raw).exists("preserved");
        verifyNoMoreInteractions(raw);
        server.verify();
    }
}
