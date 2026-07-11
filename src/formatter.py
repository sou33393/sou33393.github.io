"""
수집된 뉴스를 카테고리별로 정리하고, 카카오톡 메시지용 미리보기 텍스트를 만드는 모듈
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from config import BIGTECH_RSS_SOURCES, CATEGORIES, POLICY_RSS_SOURCES, NewsCategory, Settings
from news_service import Article
from rss_service import latest_within_window

KST = ZoneInfo("Asia/Seoul")

# 카카오 text 템플릿 실제 제한(200자)에 맞추기 위한 헤드라인 미리보기 길이
_HEADLINE_PREVIEW_MAX_LENGTH = 24

# 카테고리별 헤드라인 우선 소스: (RSS 소스 목록, 출처 라벨, 파급력 키워드 가중치 사용 여부)
# 빅테크는 "공식 발표가 있으면 최우선"이라 최신순 그대로 사용하고,
# 정책은 "파급력이 가장 큰 항목"을 원하므로 headline_keywords로 가중치를 준다.
# 없는 카테고리(경제)는 네이버 기반 선정만 사용한다.
_RSS_SOURCES_BY_CATEGORY = {
    "ai_tech": (BIGTECH_RSS_SOURCES, "빅테크 공식 발표", False),
    "policy": (POLICY_RSS_SOURCES, "정부 공식 자료", True),
}

_DEFAULT_HEADLINE_SOURCE = "언론사"


def today_label() -> str:
    return datetime.now(KST).strftime("%Y년 %m월 %d일 (%a)")


def _select_headline_from_naver(articles: List[Article], keywords: List[str]) -> Optional[Article]:
    """카테고리 키워드에 가장 많이 매칭되는 기사를 헤드라인으로 선정합니다 (동점이면 최신 기사)."""
    if not articles:
        return None
    if not keywords:
        return articles[0]

    def score(article: Article) -> int:
        haystack = article.title + " " + article.description
        return sum(1 for keyword in keywords if keyword in haystack)

    # articles는 news_service에서 이미 최신순으로 정렬돼 있으므로,
    # max()는 동점일 때 더 최신 기사를 유지한다.
    return max(articles, key=score)


@dataclass
class CategoryBriefing:
    category: NewsCategory
    headline: Optional[Article]
    headline_source: str  # 예: "정부 공식 자료 · 국토교통부", "빅테크 공식 발표 · OpenAI", "언론사"
    rest: List[Article]

    @property
    def total_count(self) -> int:
        return (1 if self.headline else 0) + len(self.rest)


def build_category_briefings(
    articles_by_category: Dict[str, List[Article]], settings: Settings
) -> Tuple[List[CategoryBriefing], List[str]]:
    """
    카테고리별 기사 목록에서 헤드라인 1건과 나머지 목록을 분리합니다.

    AI/기술은 빅테크 공식 블로그, 사회/정책은 정부 부처 공식 RSS를 최우선으로 사용하고,
    오늘 새 발표가 없으면(=max_article_age_hours 기준 이내 항목이 없으면) 네이버 검색
    결과 기반 키워드 매칭으로 자동 폴백합니다.

    반환값은 (카테고리별 브리핑 목록, 수집에 실패한 RSS 소스 라벨 목록) 입니다.
    """
    briefings = []
    failed_sources: List[str] = []

    for category in CATEGORIES:
        articles = articles_by_category.get(category.key, [])
        rss_config = _RSS_SOURCES_BY_CATEGORY.get(category.key)

        headline: Optional[Article] = None
        headline_source = _DEFAULT_HEADLINE_SOURCE
        rest = articles

        if rss_config:
            sources, label_prefix, use_impact_keywords = rss_config
            impact_keywords = category.headline_keywords if use_impact_keywords else None
            rss_item, failed = latest_within_window(sources, settings, impact_keywords=impact_keywords)
            failed_sources.extend(failed)
            if rss_item:
                headline = Article(
                    title=rss_item.title, link=rss_item.link, description="", published_at=rss_item.published_at
                )
                headline_source = f"{label_prefix} · {rss_item.source_label}"
                rest = articles[: max(category.max_items - 1, 0)]

        if headline is None:
            headline = _select_headline_from_naver(articles, category.headline_keywords)
            rest = [article for article in articles if article is not headline]

        briefings.append(
            CategoryBriefing(category=category, headline=headline, headline_source=headline_source, rest=rest)
        )
    return briefings, failed_sources


def _truncate(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    return text[:max_length].rstrip() + "…"


def build_preview_text(briefings: List[CategoryBriefing], today: str, failed_sources: Optional[List[str]] = None) -> str:
    """
    카카오톡 알림용 짧은 미리보기 텍스트를 만듭니다.
    카테고리별 헤드라인 제목 + "그 외 N건"만 담고, 전체 목록은 브리핑 페이지 링크로 안내합니다.
    (카카오 text 템플릿 실제 제한: 최대 200자)

    failed_sources가 있으면(=일부 데이터 소스 수집이 실패했으면) 짧은 경고를 덧붙입니다.
    "오늘 새 발표가 없어 폴백"은 정상 동작이라 여기 포함되지 않습니다 — 실제 수집 실패만 표시됩니다.
    """
    lines = [f"📰 오늘의 브리핑 - {today}"]
    for briefing in briefings:
        if briefing.headline is None:
            lines.append(f"{briefing.category.label} 소식 없음")
            continue
        title = _truncate(briefing.headline.title, _HEADLINE_PREVIEW_MAX_LENGTH)
        extra = len(briefing.rest)
        suffix = f" (+그 외 {extra}건)" if extra > 0 else ""
        lines.append(f"{briefing.category.label} {title}{suffix}")

    if failed_sources:
        unique = sorted(set(failed_sources))
        lines.append(f"⚠️ 소스 오류: {', '.join(unique)}")

    return "\n".join(lines)
