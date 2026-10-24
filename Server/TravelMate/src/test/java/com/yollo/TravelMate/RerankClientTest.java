package com.yollo.TravelMate;

import java.util.List;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import com.yollo.TravelMate.ai.rerank.base.RerankClient;
import com.yollo.TravelMate.ai.rerank.base.RerankClient.Scored;
import com.yollo.TravelMate.domain.place.data.result.PlaceResult;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 재랭킹이 "문체는 비슷한데 주제는 다른" 오탐(서래마을류)을 실제로 걸러내는지, 그리고
 * 재랭킹을 거쳐도 PlaceResult 레코드 전체(id, tourContentId 등)가 그대로 살아있는지 확인하는 테스트.
 * 고정 더미 데이터를 쓴다 - 다른 테스트(수집/가공)가 먼저 돌아서 DB에 데이터가 쌓여있어야 하는
 * 의존성 없이, 재랭킹 로직 자체(순서, 레코드 보존)만 독립적으로 검증하기 위함.
 */
@SpringBootTest
class RerankClientTest {

    @Autowired
    RerankClient rerankClient;

    @Test
    void 역사공부_쿼리에서_서래마을이_최하위로_밀려야한다() {
        String query = "역사 공부하기 좋은 장소";

        PlaceResult gyeongGyunGwan = placeResult(1L, "성균관 명륜당", "tc-1",
                "관광지. 기타역사유적지. 조선시대 대표적인 교육기관인 성균관은 학교와 사당의 역할을 동시에 수행한 곳이다. "
                        + "성균관의 학생들이 학문을 익히고 연구하며 왕세자까지 교육한 최고의 학부를 명륜당이라고 부른다.");
        PlaceResult dobongSeowon = placeResult(2L, "도봉서원(서울)", "tc-2",
                "관광지. 사당. 도봉서원은 조선 전·후기의 가장 대표적인 성리학자인 조광조와 송시열을 배향한 사액서원으로 "
                        + "백사 이항복 등 저명한 시인 묵객들이 시문을 남긴 오늘날 서울 지역 내 가장 대표적인 서원이다.");
        PlaceResult dongdaemunPark = placeResult(3L, "동대문역사문화공원", "tc-3",
                "관광지. 주제공원. 동대문역사문화공원은 서울특별시 중구의 옛 동대문운동장 자리에 조성한 공원이다. "
                        + "서울의 옛 역사와 문화를 보여주는 테마공원이자, 조선시대의 서울성곽인 이간수문과 치성, "
                        + "하도감과 훈련도감 터를 비롯한 건물지 유구 44기가 출토되었다.");
        PlaceResult mugyewon = placeResult(4L, "종로 무계원", "tc-4",
                "관광지. 민속마을. 무계원은 서울 종로구 부암동에 위치한 전통문화 공간으로, 과거 안평대군의 별장이 있던 자리이다. "
                        + "한옥으로 조성된 이곳은 전시, 공연, 교육 등 다양한 전통문화 프로그램을 통해 한국의 아름다움을 체험할 수 있는 장소이다.");
        PlaceResult seoraeMaeul = placeResult(5L, "서래마을", "tc-5",
                "관광지. 마을관광지. 마을 앞의 개울이 서리서리 굽이쳐 흐른다는 의미의 서래마을은 프랑스풍의 다양한 레스토랑과 "
                        + "카페, 와인바, 상점들을 만나볼 수 있는 곳이다. 1985년 주한 프랑스학교가 이곳으로 이전하면서부터 "
                        + "서래마을이 프랑스인들의 거주지역으로 자리 잡게 되었다.");

        List<PlaceResult> candidates = List.of(
                gyeongGyunGwan, dobongSeowon, dongdaemunPark, mugyewon, seoraeMaeul);

        List<Scored<PlaceResult>> ranked = rerankClient.rerank(query, candidates, PlaceResult::description);

        System.out.println("=== 재랭킹 결과 (" + query + ") ===");
        for (Scored<PlaceResult> s : ranked) {
            System.out.printf("%.4f  id=%d tourContentId=%s %s%n",
                    s.score(), s.candidate().id(), s.candidate().tourContentId(), s.candidate().name());
        }

        // 반환 개수는 입력과 같아야 하고, 점수 내림차순 정렬이어야 한다.
        assertEquals(candidates.size(), ranked.size());
        for (int i = 0; i < ranked.size() - 1; i++) {
            assertTrue(ranked.get(i).score() >= ranked.get(i + 1).score(), "점수 내림차순 정렬이어야 함");
        }

        // 핵심 검증 1: 서래마을이 최하위(마지막)여야 한다.
        PlaceResult last = ranked.get(ranked.size() - 1).candidate();
        assertEquals(seoraeMaeul.id(), last.id());
        assertEquals(seoraeMaeul.tourContentId(), last.tourContentId());

        // 핵심 검증 2: 진짜 역사/교육 장소(성균관 명륜당)가 1위여야 하고, 텍스트만이 아니라
        // id/tourContentId 같은 다른 필드도 재랭킹 과정에서 손상 없이 그대로 살아있어야 한다.
        PlaceResult first = ranked.get(0).candidate();
        assertEquals(gyeongGyunGwan.id(), first.id());
        assertEquals(gyeongGyunGwan.tourContentId(), first.tourContentId());
        assertEquals(gyeongGyunGwan.region(), first.region());
        assertEquals(gyeongGyunGwan.latitude(), first.latitude());
    }

    private static PlaceResult placeResult(Long id, String name, String tourContentId, String description) {
        return new PlaceResult(
                id, name, description,
                "서울", "종로", "관광지", "역사유적",
                37.5826, 126.9996, // 위경도는 검증용 더미값(성균관 인근 좌표)
                null, tourContentId, null, null);
    }
}
