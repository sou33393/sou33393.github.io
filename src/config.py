"""
설정 및 환경 변수 관리 모듈

모든 민감 정보(API 키, 토큰)는 환경 변수에서 로드합니다.
절대 코드에 하드코딩하지 마세요.
"""
import os
from dataclasses import dataclass, field
from typing import List

from dotenv import load_dotenv

load_dotenv()


def _require_env(key: str) -> str:
    """필수 환경 변수를 가져오고, 없으면 명확한 에러를 발생시킵니다."""
    value = os.environ.get(key)
    if not value:
        raise RuntimeError(
            f"필수 환경 변수 '{key}'가 설정되지 않았습니다. "
            f".env 파일 또는 GitHub Actions Secrets를 확인하세요."
        )
    return value


def _default_page_url() -> str:
    """
    브리핑 페이지 URL을 결정합니다.

    BRIEFING_PAGE_URL이 명시돼 있으면 그 값을 쓰고, 없으면 GitHub Actions가
    자동 주입하는 GITHUB_REPOSITORY("owner/repo")로 GitHub Pages 주소를 계산합니다.
    """
    explicit = os.environ.get("BRIEFING_PAGE_URL")
    if explicit:
        return explicit

    repo = os.environ.get("GITHUB_REPOSITORY")
    if repo and "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner}.github.io/{name}/"

    return "https://example.com/"


@dataclass(frozen=True)
class NewsCategory:
    """뉴스 카테고리 정의"""
    key: str
    label: str          # 사람이 읽는 표시명 (이모지 포함)
    queries: List[str]  # 검색 키워드 목록
    color: str = "#6b7280"           # 카테고리 색상 (브리핑 페이지 강조색)
    max_items: int = 6               # 카테고리당 최대 기사 수 (헤드라인 1건 포함)
    headline_keywords: List[str] = field(default_factory=list)  # 헤드라인 우선 선정 키워드


@dataclass(frozen=True)
class Settings:
    # 네이버 검색 API (https://developers.naver.com 에서 무료 발급)
    naver_client_id: str = field(default_factory=lambda: _require_env("NAVER_CLIENT_ID"))
    naver_client_secret: str = field(default_factory=lambda: _require_env("NAVER_CLIENT_SECRET"))

    # 카카오 API (https://developers.kakao.com 에서 발급)
    kakao_rest_api_key: str = field(default_factory=lambda: _require_env("KAKAO_REST_API_KEY"))
    kakao_refresh_token: str = field(default_factory=lambda: _require_env("KAKAO_REFRESH_TOKEN"))

    # 한국은행 ECOS API (https://ecos.bok.or.kr 에서 발급)
    ecos_api_key: str = field(default_factory=lambda: _require_env("ECOS_API_KEY"))

    # 토큰 캐시 파일 경로 (GitHub Actions에서는 캐시/아티팩트로 영속화 권장)
    token_cache_path: str = os.environ.get("KAKAO_TOKEN_CACHE_PATH", ".kakao_tokens.json")

    # ECOS 수치 캐시 파일 경로. 하루 1회만 호출하고 같은 날 재실행 시 재사용합니다.
    ecos_cache_path: str = os.environ.get("ECOS_CACHE_PATH", ".ecos_cache.json")

    # 브리핑 웹페이지 URL (GitHub Pages). 카카오 메시지의 링크 버튼에 사용됩니다.
    briefing_page_url: str = field(default_factory=_default_page_url)

    # 기사 검색 시 최근 며칠 이내 뉴스만 허용할지 (0이면 제한 없음)
    max_article_age_hours: int = int(os.environ.get("MAX_ARTICLE_AGE_HOURS", "30"))

    # HTTP 요청 타임아웃(초)
    request_timeout: int = int(os.environ.get("REQUEST_TIMEOUT", "10"))

    # 재시도 횟수
    max_retries: int = int(os.environ.get("MAX_RETRIES", "3"))


CATEGORIES: List[NewsCategory] = [
    NewsCategory(
        key="ai_tech",
        label="🤖 AI/기술",
        queries=["생성형 AI", "AI 신규 모델 출시", "AI 반도체"],
        color="#7c3aed",  # 보라
        max_items=6,
        # 빅테크 공식 발표 우선 (회사명이 실제로 언급된 기사만 매칭되도록 회사명만 사용 —
        # "발표"/"공개" 같은 일반 단어는 무관한 기사에도 매칭돼 제외함)
        headline_keywords=[
            "오픈AI", "OpenAI", "챗GPT", "ChatGPT", "구글", "Google", "메타", "Meta",
            "마이크로소프트", "Microsoft", "애플", "Apple", "엔비디아", "NVIDIA",
            "삼성전자", "네이버", "카카오", "아마존", "Amazon", "테슬라", "Tesla", "앤스로픽", "Anthropic",
        ],
    ),
    NewsCategory(
        key="economy",
        label="💰 경제/금융",
        queries=["기준금리", "원달러 환율", "코스피 시황"],
        color="#d97706",  # 앰버
        max_items=6,
        # 코스피/코스닥/환율 등 수치 지표 우선
        headline_keywords=["코스피", "코스닥", "환율", "원달러", "원·달러", "원/달러", "기준금리", "금리"],
    ),
    NewsCategory(
        key="policy",
        label="🏠 사회/정책",
        queries=["부동산 정책", "세금 개편", "노동법 개정"],
        color="#0d9488",  # 틸
        max_items=6,
        # 정부 정책 발표 우선 ("발표"는 무관한 기사(실적 발표 등)에도 매칭돼 제외함)
        headline_keywords=["정부", "정책", "국회", "법안", "규제", "개편", "대책"],
    ),
]


# 사회/정책 카테고리 헤드라인용 정부 부처 RSS.
# korea.kr 통합 RSS는 서비스가 중단되어(2026-07 확인) 부처별 공식 도메인 RSS를 직접 사용합니다.
# (department_label, rss_url)
POLICY_RSS_SOURCES = [
    ("기획재정부", "https://mofe.go.kr/com/detailRssTagService.do?bbsId=MOSFBBS_000000000028"),
    ("국토교통부", "https://www.molit.go.kr/dev/board/board_rss.jsp?rss_id=NEWS"),
    ("고용노동부", "https://www.moel.go.kr/rss/policy.do"),
]

# AI/기술 카테고리 헤드라인용 빅테크 공식 블로그 RSS.
# Anthropic은 공식 RSS를 제공하지 않아(2026-07 확인) 제외했습니다 —
# 관련 소식은 기존 네이버 검색 + headline_keywords 매칭으로 커버됩니다.
# (company_label, rss_url)
BIGTECH_RSS_SOURCES = [
    ("OpenAI", "https://openai.com/news/rss.xml"),
    ("Google DeepMind", "https://deepmind.google/blog/rss.xml"),
]


def get_settings() -> Settings:
    return Settings()
