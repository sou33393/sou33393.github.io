"""
매일 아침 뉴스 브리핑 → 카카오톡 발송 파이프라인

실행 방법:
    python src/main.py

환경 변수는 .env 파일 또는 시스템 환경 변수(GitHub Actions Secrets)로 주입합니다.
자세한 설정 방법은 README.md를 참고하세요.

카카오 "text" 템플릿은 최대 200자만 지원하고, 링크 버튼은 사전 등록된 도메인으로만
이동할 수 있어 매일 바뀌는 언론사 링크를 직접 담을 수 없다. 대신 기사 목록은
GitHub Pages 브리핑 페이지(docs/index.html)로 만들어 배포하고, 카카오톡에는
그 페이지 링크가 담긴 짧은 알림 1건만 보낸다.
"""
import logging
import sys
from pathlib import Path

from config import get_settings
from ecos_client import get_daily_snapshot
from formatter import build_category_briefings, build_preview_text, today_label
from kakao_client import send_text_message
from kakao_token_manager import KakaoTokenManager
from news_service import fetch_all_categories
from page_builder import render_page, write_page

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("daily_briefing")


def run() -> int:
    """
    전체 파이프라인을 실행합니다.

    Returns:
        int: 프로세스 종료 코드 (0=성공, 1=실패). GitHub Actions에서
             실패를 감지해 알림을 보내려면 이 값을 활용하세요.
    """
    try:
        settings = get_settings()
    except RuntimeError as exc:
        logger.error("설정 오류: %s", exc)
        return 1

    try:
        logger.info("=== 일일 브리핑 파이프라인 시작 ===")

        articles_by_category = fetch_all_categories(settings)
        briefings, failed_sources = build_category_briefings(articles_by_category, settings)
        today = today_label()

        try:
            ecos_snapshot = get_daily_snapshot(settings)
        except Exception:
            logger.exception("ECOS 지표 조회 실패, 경제 수치 블록 없이 진행합니다.")
            ecos_snapshot = None
            failed_sources.append("한국은행 ECOS")

        html = render_page(briefings, today, ecos_snapshot)
        write_page(html, Path("docs/index.html"))
        logger.info("브리핑 페이지 생성 완료: docs/index.html")

        has_content = any(b.headline for b in briefings)
        token_manager = KakaoTokenManager(settings)

        if has_content:
            text = build_preview_text(briefings, today, failed_sources)
        else:
            text = f"⚠️ 오늘의 브리핑 - {today}\n수집된 뉴스가 없습니다. 검색어 설정을 확인해주세요."

        send_text_message(text, settings, token_manager, link_url=settings.briefing_page_url)

        logger.info("=== 파이프라인 성공적으로 완료 ===")
        return 0

    except Exception:
        logger.exception("파이프라인 실행 중 예상치 못한 오류 발생")
        return 1


if __name__ == "__main__":
    sys.exit(run())
