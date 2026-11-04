package com.yollo.TravelMate.domain.conversation.service;

/**
 * Why the server could not finish the branch LiLi chose. Only the Korean situation reaches LiLi's follow-up;
 * the constant name stays inside the server so she never reads an internal code aloud.
 */
public enum LiliServerCode {
    PLANNING_CONDITIONS_MISSING("일정을 만들 날짜·시간·지역 같은 조건이 아직 없어서 일정을 만들지 않았다. 필요한 조건을 물어봐야 한다.", true),
    JOB_ID_NOT_FOUND("사용자 말에 확인할 일정 생성 작업 번호가 없어서 조회하지 않았다. 어떤 작업인지 물어봐야 한다.", true),
    DISPLAYED_RESULT_MISSING("지금 화면에 보이는 추천 목록이 전달되지 않아 몇 번째 장소를 말하는지 알 수 없다. 어떤 장소를 뺄지 물어봐야 한다.", true),
    EXCLUDE_POSITION_OUT_OF_RANGE("말한 순번의 장소가 지금 보이는 추천 목록에 없다. 어떤 장소를 뺄지 다시 물어봐야 한다.", true),
    PLAN_REQUEST_FAILED("일정 생성을 접수하지 못했다.", false),
    JOB_LOOKUP_FAILED("일정 생성 작업을 확인하지 못했다.", false),
    PLAN_GENERATION_FAILED("요청한 일정 생성 작업이 끝나지 못하고 실패했다.", false);

    private final String situation;
    private final boolean needsUserInput;

    LiliServerCode(String situation, boolean needsUserInput) {
        this.situation = situation;
        this.needsUserInput = needsUserInput;
    }

    public String situation() {
        return situation;
    }

    /** Missing input is a question back to the user, so the follow-up may offer choices; failures may not. */
    public boolean needsUserInput() {
        return needsUserInput;
    }
}
