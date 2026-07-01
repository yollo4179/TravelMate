package com.yollo.TravelMate.domain.place.enums;

import java.util.List;

public enum PlaceCategory {

    자연경관("자연·경관", List.of(
        "전망대", "공원", "수목원", "해수욕장", "계곡", "폭포", "자연휴양림"
    )),

    역사문화("역사·문화", List.of(
        "고궁", "사찰", "유적지", "한옥마을", "종묘", "성곽", "왕릉"
    )),

    전시예술("전시·예술", List.of(
        "박물관", "미술관", "전시관", "공연장", "과학관"
    )),

    체험액티비티("체험·액티비티", List.of(
        "테마파크", "동물원", "아쿠아리움", "워터파크", "케이블카", "짚라인"
    )),

    먹거리("먹거리", List.of(
        "맛집", "전통시장", "먹자골목"
    )),

    카페디저트("카페·디저트", List.of(
        "카페", "베이커리", "찻집"
    )),

    쇼핑("쇼핑", List.of(
        "백화점", "쇼핑몰", "아울렛", "시장"
    )),

    휴양숙박("휴양·숙박", List.of(
        "호텔", "리조트", "펜션", "온천", "스파"
    ));

    private final String label;
    private final List<String> keywords;

    PlaceCategory(String label, List<String> keywords) {
        this.label = label;
        this.keywords = keywords;
    }

    public String getLabel() {
        return label;
    }

    public List<String> getKeywords() {
        return keywords;
    }
}