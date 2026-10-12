# 검색 툴 설계 (거리 기반 + 의미 기반)

> **배경**: 임베딩 노이즈 분석 결과, 음식점(39)/숙박(32)은 `detailInfo2`가 화장실 유무 등
> 활동과 무관한 정보만 주고(음식점), 숙박은 필드 스키마가 달라 애초에 파싱조차 안 됨.
> 두 카테고리는 애초에 "테마/활동 의미검색"보다 "근처에서 가까운 곳" 검색에 더 맞는
> 카테고리라 판단하여, 벡터 검색과 별도로 **거리 기반 검색 툴**을 설계했다(1~6장).
> 이후 실제 임베딩 테스트에서 지역명+테마를 한 문장으로 합쳐서 검색하면 지역명 텍스트가
> 테마 신호를 오염시킨다는 게 실증되어, **의미 기반 검색도 같은 이유로 tool calling으로
> 빼고 지역/카테고리를 구조화 파라미터로 분리**하기로 했다(7장).
> **관련 문서**: `travel_app_screen_structure.md`(Tool calling + RAG 언급), `chat_persistence_options.md`

**작성일**: 2026-07-12
**버전**: v1.1 (설계 단계 — 아직 구현/연결 전. v1.1에서 의미검색 툴 스펙 추가)

---

## 1. 현재 상태 확인 (설계 전 제약사항)

| 항목 | 현재 상태 | 설계에 미치는 영향 |
|---|---|---|
| 좌표 컬럼 | `places.latitude`, `places.longitude` (double, PostGIS 아님) | 거리 계산은 Haversine 공식을 SQL에서 직접 계산 |
| Tool calling | `LlmClient.generate(systemPrompt, userPrompt)` — 텍스트 in/out만 있음, Ollama `tools` 파라미터 미사용 | 이 문서의 "툴 스펙"은 아직 LLM에 연결되지 않은 설계도. `LlmClient` 확장이 선행 작업으로 필요 |
| 카테고리 라벨 | TourAPI: `category="음식점"/"숙박"` · Kakao: `category="먹거리"/"휴양·숙박"` (서로 다른 어휘) | 필터링 시 두 어휘를 하나로 매핑하는 상수 테이블 필요 |
| 평점/리뷰 | 수집 데이터에 없음 (Kakao 키워드검색, TourAPI 둘 다 rating 필드 없음) | 정렬 기준은 거리 하나뿐 (평점순은 향후 별도 데이터 소스 필요) |
| 인덱스 | `latitude`/`longitude`에 인덱스 없음 | bounding box 사전 필터용 btree 인덱스 추가 필요 |

---

## 2. 거리 계산 방식 결정

| 방식 | 장점 | 단점 | 채택 |
|---|---|---|---|
| **PostGIS + geography 컬럼** | 가장 정확·빠름, `ST_DWithin`으로 인덱스 활용 | 확장 설치 + 컬럼 추가 + 백필 마이그레이션 필요, 인프라 변경 | 보류 (2순위) |
| **Haversine SQL + bounding box 사전필터** | 기존 스키마 그대로 사용, 신규 의존성 없음 | 대량 데이터에서 PostGIS보다 느림 (지금 규모에선 충분) | **채택 (1순위)** |
| **Java에서 전체 로드 후 거리 계산** | 구현 단순 | 매 요청마다 전체 places 스캔 — 스케일 안 됨 | 기각 |

**결정**: `chat_persistence_options.md`에서 이미 "기존 스택 일관성 + 자체 통제"를 최우선 가치로 잡았으므로,
지금 단계에서는 신규 확장(PostGIS) 없이 **Haversine + bounding box 사전필터**로 간다.
데이터 규모가 커지면(수십만 건 이상) PostGIS 전환을 재검토.

---

## 3. SQL 설계

Bounding box를 Java에서 미리 계산해 WHERE절로 후보를 좁힌 뒤, Haversine으로 정확한 거리를 구해 정렬한다.
(위도 1도 ≈ 111km, 경도 1도 ≈ 111km × cos(위도) — 극지방 근처가 아니라서 근사로 충분)

```sql
select id, name, description, region, city, category, source_category,
       latitude, longitude, image_url, homepage_url,
       ( 6371 * acos(
           least(1.0, greatest(-1.0,
             cos(radians(?)) * cos(radians(latitude)) *
             cos(radians(longitude) - radians(?)) +
             sin(radians(?)) * sin(radians(latitude))
           ))
       ) ) as distance_km
from places
where latitude  between ? and ?
  and longitude between ? and ?
  and category = ANY(?)
order by distance_km
limit ?
```

- `least/greatest`로 부동소수점 오차로 인한 `acos` 정의역(NaN) 이탈 방지
- `category = ANY(?)`는 아래 4장의 카테고리 매핑 테이블로 만든 문자열 배열을 받음
- bounding box(`latitude/longitude between`)가 실제 필터 역할, `distance_km`는 그 안에서 정확 정렬용

**인덱스 추가 필요**:
```sql
create index idx_places_lat_lng on places (latitude, longitude);
```

---

## 4. 카테고리 어휘 매핑

소스별로 라벨이 달라서 "음식점 근처 검색"을 하려면 두 어휘를 다 포함해야 한다.

```java
// 신규: com.yollo.TravelMate.domain.place.enums.NearbySearchCategory (가칭)
public enum NearbySearchCategory {
    RESTAURANT(List.of("음식점", "먹거리", "카페·디저트")),
    LODGING(List.of("숙박", "휴양·숙박"));

    private final List<String> categoryLabels; // places.category IN (...)에 사용
}
```

> 카페를 음식점에 포함할지는 제품 판단 필요 — 일단 후보로만 넣어둠.

---

## 5. Repository / Service 인터페이스

`PlaceVectorRepository`에 벡터 검색과 별개로 추가 (기존 `searchSimilar*`는 그대로 유지):

```java
// PlaceVectorRepository.java 추가분
public List<PlaceNearbyResult> searchNearby(
        double centerLat, double centerLng, double radiusKm,
        List<String> categoryLabels, int limit) {
    double latDelta = radiusKm / 111.0;
    double lngDelta = radiusKm / (111.0 * Math.cos(Math.toRadians(centerLat)));
    // ... SQL 3장 그대로, PLACE_NEARBY_ROW_MAPPER 사용
}

public record PlaceNearbyResult(
        Long id, String name, String description, String region, String city,
        String category, String sourceCategory,
        Double latitude, Double longitude, Double distanceKm,
        String tourContentId, String imageUrl, String homepageUrl
) {}
```

`similarity` 대신 `distanceKm`을 쓰는 별도 record로 분리한다 — 기존 `PlaceResult`(벡터검색 결과)를 억지로
재사용하면 벡터검색 호출부에서 `similarity`가 null인 케이스를 방어 코드로 처리해야 해서 오히려 지저분해짐.

`CandidateFormatter`도 오버로드 추가해서 `distanceKm` 버전을 LLM 프롬프트용 텍스트로 포맷팅
(예: `"| 거리: 320m"` 또는 `"| 거리: 1.2km"`).

---

## 6. Tool Calling 스펙 — 거리 기반 `search_nearby_places` (설계만 — 아직 미연결)

Ollama `/api/chat`의 `tools` 파라미터에 넣을 함수 정의. **`LlmClient`/`OllamaLlmClient`가 지금
tools 파라미터를 아예 안 받으므로, 이 스펙을 실제로 쓰려면 그 인터페이스 확장이 선행되어야 한다.**

```json
{
  "type": "function",
  "function": {
    "name": "search_nearby_places",
    "description": "특정 좌표 근처의 음식점/숙박을 거리순으로 검색한다. 테마·활동 기반 추천(도자기 체험, 역사 탐방 등)에는 쓰지 말고, '근처 맛집', '이 근처 숙소 추천' 같은 위치 기반 요청에만 사용한다.",
    "parameters": {
      "type": "object",
      "properties": {
        "centerLat":  { "type": "number", "description": "검색 중심 위도 (현재 위치 또는 선택된 마커)" },
        "centerLng":  { "type": "number", "description": "검색 중심 경도" },
        "radiusKm":   { "type": "number", "description": "검색 반경(km). 기본값 2" },
        "category":   { "type": "string", "enum": ["RESTAURANT", "LODGING"] },
        "limit":      { "type": "integer", "description": "최대 결과 수. 기본값 10" }
      },
      "required": ["centerLat", "centerLng", "category"]
    }
  }
}
```

### 라우팅 규칙 (시스템 프롬프트에 명시할 내용, 7장 `search_places_semantic`과 공통)

- 사용자 요청이 **활동/테마**(체험, 역사, 자연, 문화 등) → `search_places_semantic` 사용, 지역명은 `city`/`region` 파라미터로 분리
- 사용자 요청이 **음식점/숙박** 관련 → `search_nearby_places` 사용
- `centerLat/centerLng`는 `travel_app_screen_structure.md`의 `currentFocusMarkerId` 또는 사용자 현재 위치에서 가져옴 (Android가 GPS 또는 선택된 마커 좌표를 함께 전송)

---

## 7. 의미 기반 검색 툴 (`search_places_semantic`)

### 7.1 왜 필요한가 — 실증 데이터

실제 임베딩 데이터(서울 관광지 449건)로 두 가지 방식을 비교 테스트했다.

**A안 — 지역명+테마를 한 문장으로 합쳐서 임베딩** (`"종로 역사 공부하기 좋은 장소"` 그대로 임베딩 후 `searchSimilarTopK`, 필터 없음)

| 순위 | 장소 | 유사도 | 문제 |
|---|---|---|---|
| 2 | 서울 종로 낙지볶음 골목 | 0.5441 | 음식 골목. 역사/공부와 무관, "종로" 텍스트만 겹침 |
| 7 | 세종마을 음식문화거리 | 0.5174 | 위와 동일 |
| 8 | 동대문역사문화공원 | 0.5105 | **진짜 좋은 매칭인데 종로가 아니라서 순위 밀림** |
| 9 | 도봉서원 | 0.4994 | 위와 동일 (조선시대 서원, 역사 공부에 정확히 맞음) |

**B안 — city를 SQL 필터로 분리, 순수 테마("역사 공부하기 좋은 장소")만 임베딩** (`searchSimilar(embedding, region=null, city="종로", ...)`)

| 순위 | 장소 | 유사도 |
|---|---|---|
| 1 | 성균관 명륜당 | **0.5212** (A안 1위였던 0.4474보다 훨씬 높음) |
| 3 | 경희궁공원 | 0.4710 (A안에는 아예 없던 좋은 매칭이 새로 드러남) |

음식 골목류 노이즈가 완전히 사라졌고, 1위 유사도 자체도 0.4474 → 0.5212로 크게 올랐다.
**결론: 지역명 텍스트가 임베딩 안에 섞이면 테마 신호를 오염시킨다.** `PlaceVectorRepository.searchSimilar()`는
이미 `region`/`city`/`category`를 구조화 파라미터로 받게 되어 있으므로(코드 변경 불필요), 호출부(LLM tool call)에서
**지역/카테고리와 순수 테마 쿼리를 분리해서 넘기기만 하면 된다.**

### 7.2 Tool Calling 스펙

```json
{
  "type": "function",
  "function": {
    "name": "search_places_semantic",
    "description": "테마·활동 기반으로 관광지를 의미검색한다 (예: 체험, 역사, 자연, 전통문화). 음식점/숙박 근처 검색에는 쓰지 말고 search_nearby_places를 사용한다. 지역명이 요청에 포함돼 있으면 반드시 city/region 파라미터로 분리해서 넣고, query에는 순수 테마만 남긴다 (지역명을 query에 같이 넣으면 검색 품질이 떨어짐 - 실측으로 확인됨).",
    "parameters": {
      "type": "object",
      "properties": {
        "query":    { "type": "string", "description": "테마/활동 키워드만. 지역명 절대 포함 금지. 예: '역사 공부하기 좋은 장소', '전통문화 체험'" },
        "region":   { "type": "string", "description": "광역 지역명(선택). 예: 서울, 부산" },
        "city":     { "type": "string", "description": "시군구명(선택). 예: 종로, 강남" },
        "category": { "type": "string", "description": "카테고리(선택). 예: 관광지, 문화시설" },
        "limit":    { "type": "integer", "description": "최대 결과 수. 기본값 10" }
      },
      "required": ["query"]
    }
  }
}
```

### 7.3 인터페이스

`PlaceVectorRepository.searchSimilar()`는 이미 존재하므로 그대로 재사용한다. 새로 필요한 건 이 함수 호출을
받아서 `query`만 임베딩하고 나머지는 그대로 SQL 파라미터로 넘기는 서비스 메서드 하나뿐이다.

```java
// 신규: PlaceSemanticSearchService (가칭)
public List<PlaceResult> searchByTool(String query, String region, String city, String category, int limit) {
    float[] embedding = embeddingClient.embed(query);   // query만 임베딩, region/city는 안 섞음
    return placeRepository.searchSimilar(embedding, region, city, category, 0.0, limit);
}
```

---

## 8. 구현 순서 (다음 단계, 통합)

**거리 기반 (`search_nearby_places`)**
1. `places (latitude, longitude)` 인덱스 추가
2. `NearbySearchCategory` enum + `PlaceVectorRepository.searchNearby()` + `PlaceNearbyResult`
3. `CandidateFormatter`에 거리 기반 포맷 오버로드 추가
4. (선택) REST 엔드포인트로 먼저 노출해서 단독 테스트 — 예: `GET /api/places/nearby?lat=..&lng=..&category=RESTAURANT&radiusKm=2`

**의미 기반 (`search_places_semantic`)**
5. `PlaceSemanticSearchService.searchByTool()` 추가 (기존 `searchSimilar()` 재사용, 신규 로직 거의 없음)
6. (선택) REST 엔드포인트로 먼저 노출해서 단독 테스트

**공통 (두 툴 다 필요)**
7. `LlmClient` 인터페이스에 tools 파라미터 확장 (`generate(system, user, tools)` 또는 별도 메서드) — **선행 인프라 작업, 별도 논의 필요. 두 툴이 이 작업 하나를 공유하므로 한 번에 처리하는 게 효율적**
8. 7장(`search_places_semantic`)·6장(`search_nearby_places`) 스펙으로 Ollama tool calling 연결 + 시스템 프롬프트 라우팅 규칙 추가
9. Android: 현재 위치/선택 마커 좌표를 Chat 요청에 포함하도록 연동

---

## 9. 열린 질문

- 카페(`카페·디저트`)를 RESTAURANT에 포함시킬지 — 제품 판단 필요
- 반경 기본값(2km)이 적절한지 — 도심/외곽에 따라 다를 수 있어 동적 조정 고려 가능
- 평점 데이터가 없는 상태로 "맛집 추천"이 설득력 있는지 — 필요시 카카오 리뷰 수 필드 등 추가 수집 검토
- `search_places_semantic`에서 지역/카테고리 텍스트 오염 문제는 해결했지만, "서래마을"류(문체는 비슷한데
  주제는 다른) 오탐은 순수 벡터 검색의 한계로 남아있음 — 재랭킹(cross-encoder) 또는 쿼리 재작성(HyDE) 필요.
  LLM이 tool call 인자를 구성하는 과정 자체가 쿼리 재작성 역할을 어느 정도 대신할 수 있어 우선순위는 낮춤.
