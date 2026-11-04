"""Reproducible client contract checks; all API calls use explicit synthetic fixtures."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.async_api import async_playwright
from browser_types import BrowserScenario

ROOT = Path(__file__).resolve().parents[3]
JOB_ID = "00000000-0000-4000-8000-000000000001"


class BrowserFixtures:
    # 각 Enum과 응답 생성 함수는 쌍이다. 실제 모델·DB의 결과로 사용하지 않는다.
    ENTRIES = (
        (BrowserScenario.CONVERSATION, lambda body: {
            "type": "TEXT", "intent": "CONVERSATION", "emotion": "HAPPY",
            "message": "다음 여행도 함께 준비해요. [모의 응답]", "items": [], "data": None, "citations": [],
        }),
        (BrowserScenario.RECOMMENDATION, lambda body: {
            "type": "PLACES", "intent": "RECOMMENDATION", "emotion": "GUIDING",
            "message": "모의 자료에서 확인한 창경궁을 추천해요.",
            "citations": [{"placeId": 378, "sourceId": "MOCK", "evidenceId": "MOCK", "quote": "모의 원문입니다."}],
            "items": [{"placeId": 378, "name": "창경궁", "region": "서울", "city": "종로",
                       "description": "브라우저 연결용 모의 자료입니다.", "latitude": 37.58, "longitude": 126.99}],
            "data": None,
        }),
        (BrowserScenario.PLAN_ACCEPTED, lambda body: {
            "type": "PLANNING_JOB", "intent": "PLAN", "emotion": "THINKING",
            "message": "초안 요청을 접수했습니다. 아직 완성되지 않았습니다. [모의 응답]",
            "items": [], "data": {"jobId": JOB_ID, "status": "QUEUED"}, "citations": [],
        }),
        (BrowserScenario.PLAN_READY, lambda body: {
            "type": "DRAFT", "intent": "PLAN", "emotion": "EXCITED",
            "message": "역사 테마의 모의 초안입니다.", "citations": [], "data": None,
            "items": [{"planId": 1, "title": "모의 역사 코스", "description": "역사 테마의 모의 초안입니다.",
                       "context": body["planningRequest"]["context"], "warnings": ["실제 경로·운영시간 미검증"],
                       "pins": [{"placeId": 378, "name": "창경궁", "stayMinutes": 60, "sequence": 1,
                                 "explanation": "선택 이유를 표시하는 모의 자료입니다."}]}],
        }),
    )
    LOOKUP = dict(ENTRIES)

    @classmethod
    def execute(cls, scenario: BrowserScenario, body: dict) -> dict:
        result = cls.LOOKUP[scenario](body)
        result.update(messageSource="SERVER_RECEIPT" if scenario in {BrowserScenario.PLAN_ACCEPTED, BrowserScenario.PLAN_READY} else "LLM",
                      termination="COMPLETED")
        if result["type"] == "PLACES":
            result["data"] = result["items"]
        if result["type"] == "DRAFT":
            result["data"] = result["items"][0]
        return result


async def check(arguments: argparse.Namespace) -> dict:
    origin = urlsplit(arguments.base_url)
    if origin.hostname not in {"127.0.0.1", "localhost"} or origin.scheme != "http" or origin.username or origin.password:
        raise ValueError("Use an explicit loopback frontend; provider/API requests are mocked")
    base = arguments.base_url.rstrip("/")
    calls, errors = [], []
    scenarios = list(BrowserScenario)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            executable_path=str(arguments.browser_executable) if arguments.browser_executable else None,
            headless=True, args=["--no-sandbox"],
        )
        page = await browser.new_page(viewport={"width": 1440, "height": 1050})
        page.on("pageerror", lambda error: errors.append(str(error)))

        async def intercept(route):
            url = route.request.url
            if "/api/auth/refresh" in url:
                await route.fulfill(json={"accessToken": "synthetic-offline-token"}); return
            if "/api/users/me" in url:
                await route.fulfill(json={"uid": "offline", "nickname": "오프라인 확인", "role": "USER", "email": "offline@example.invalid", "profileImgUrl": None}); return
            if "/api/v1/conversation/options" in url:
                await route.fulfill(json={"categories": ["관광지"]}); return
            if "/api/v1/conversation/turns" in url:
                body = route.request.post_data_json
                scenario = scenarios[len(calls)]
                calls.append(body)
                await route.fulfill(json=BrowserFixtures.execute(scenario, body)); return
            if "/api/" in url:
                errors.append("Unexpected API route"); await route.abort(); return
            if url.startswith(base + "/"):
                await route.continue_(); return
            await route.abort()

        await page.route("**/*", intercept)
        await page.goto(base + "/", wait_until="networkidle")
        await page.get_by_role("heading", name="어디로 떠나볼까요?").wait_for()
        composer = page.get_by_placeholder("가고 싶은 곳, 궁금한 점을 적어주세요…")
        await page.get_by_role("button", name="💬 대화", exact=True).click()
        await composer.fill("고마워. 다음에 또 이야기하자.")
        await page.get_by_role("button", name="메시지 전송").click()
        await page.get_by_text("다음 여행도 함께 준비해요. [모의 응답]", exact=True).wait_for()
        await page.get_by_label("여행 테마", exact=False).fill("역사, 산책")
        await page.get_by_role("button", name="📍 후보 추천", exact=True).click()
        await composer.fill("창경궁을 찾아줘.")
        await page.get_by_role("button", name="메시지 전송").click()
        await page.get_by_text("모의 자료에서 확인한 창경궁을 추천해요.", exact=True).wait_for()
        assert calls[1]["intentHint"] == "RECOMMENDATION"
        assert calls[1]["searchContext"]["themes"] == ["역사", "산책"]
        assert calls[1]["searchContext"]["area"] is None
        await page.get_by_label("기준 위치와 반경으로 제한").check()
        await page.get_by_label("위도", exact=True).fill("37.58")
        await page.get_by_label("경도", exact=True).fill("126.99")
        await page.get_by_text("일정 조건 입력", exact=True).click()
        await page.get_by_label("시작", exact=True).fill("2027-01-15T10:00")
        await page.get_by_label("종료", exact=True).fill("2027-01-15T12:00")
        await page.get_by_role("button", name="🗓 일정 만들기", exact=True).click()
        await composer.fill("역사 테마로 일정 초안을 만들어줘.")
        await page.get_by_role("button", name="메시지 전송").click()
        await page.get_by_role("button", name="작업 상태 확인").wait_for()
        assert calls[2]["planningRequest"]["context"]["transportMode"] == "WALK"
        assert calls[2]["searchContext"]["area"]["center"] == {"lat": 37.58, "lon": 126.99}
        await page.get_by_role("button", name="작업 상태 확인").click()
        await page.get_by_text("모의 역사 코스", exact=True).wait_for()
        await page.get_by_text("선택 이유를 표시하는 모의 자료입니다.", exact=True).wait_for()
        assert JOB_ID in calls[3]["message"]
        assert len(calls) == 4
        catalog = json.loads((ROOT / "Resouces/Images/LiLi/catalog.json").read_text())
        expression = next(item for item in catalog["assets"] if item["emotion"] == "EXCITED")
        assert await page.get_by_alt_text("LiLi · " + expression["visual_description"]).count() == 1
        if arguments.screenshot_dir:
            arguments.screenshot_dir.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(arguments.screenshot_dir / "desktop.png"), full_page=True)
        await page.set_viewport_size({"width": 390, "height": 844})
        if arguments.screenshot_dir:
            await page.screenshot(path=str(arguments.screenshot_dir / "mobile.png"), full_page=True)
        dimensions = await page.evaluate("({width:document.documentElement.scrollWidth, viewport:innerWidth})")
        assert dimensions["width"] <= dimensions["viewport"], dimensions
        assert not errors, errors
        await browser.close()
        return {"mode": "MOCK_BROWSER", "scenarios": [stage.value for stage in scenarios],
                "conversation_requests": len(calls), "external_requests": 0,
                "page_errors": errors, "mobile_no_horizontal_overflow": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:15173")
    parser.add_argument("--browser-executable", type=Path)
    parser.add_argument("--screenshot-dir", type=Path)
    print(json.dumps(asyncio.run(check(parser.parse_args())), ensure_ascii=False))
