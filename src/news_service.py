"""
뉴스 수집 모듈

네이버 검색 API(뉴스)를 사용해 카테고리별 최신 기사를 가져오고,
HTML 태그 제거, 중복 제거, 최신순 정렬 등을 처리합니다.

네이버 API 발급: https://developers.naver.com/apps/#/register
- 사용 API: 검색 > 뉴스
"""
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import List

from config import CATEGORIES, NewsCategory, Settings
from http_utils import request_with_retry

logger = logging.getLogger(__name__)

NAVER_NEWS_ENDPOINT = "https://openapi.naver.com/v1/search/news.json"

_TAG_RE = re.compile(r"<[^>]+>")
_BOLD_RE = re.compile(r"&quot;|&amp;|&lt;|&gt;")

_HTML_ENTITY_MAP = {
    "&quot;": '"',
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&#39;": "'",
}


@dataclass
class Article:
    title: str
    link: str
    description: str
    published_at: datetime

    def dedup_key(self) -> str:
        # 링크 기준 중복 제거 (동일 기사가 여러 키워드에 걸릴 수 있음)
        return self.link


def _clean_text(raw: str) -> str:
    text = _TAG_RE.sub("", raw)
    for entity, char in _HTML_ENTITY_MAP.items():
        text = text.replace(entity, char)
    return text.strip()


def _fetch_query(
    query: str,
    settings: Settings,
    display: int = 10,
) -> List[Article]:
    """단일 검색어에 대해 네이버 뉴스 API를 호출합니다."""
    headers = {
        "X-Naver-Client-Id": settings.naver_client_id,
        "X-Naver-Client-Secret": settings.naver_client_secret,
    }
    params = {
        "query": query,
        "display": display,
        "sort": "date",  # 최신순
    }

    response = request_with_retry(
        "GET",
        NAVER_NEWS_ENDPOINT,
        headers=headers,
        params=params,
        timeout=settings.request_timeout,
        max_retries=settings.max_retries,
    )
    payload = response.json()

    articles = []
    for item in payload.get("items", []):
        try:
            published_at = parsedate_to_datetime(item["pubDate"])
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=timezone.utc)
        except (KeyError, ValueError, TypeError):
            logger.debug("발행일 파싱 실패, 현재 시각으로 대체: %s", item.get("pubDate"))
            published_at = datetime.now(timezone.utc)

        articles.append(
            Article(
                title=_clean_text(item.get("title", "")),
                link=item.get("originallink") or item.get("link", ""),
                description=_clean_text(item.get("description", "")),
                published_at=published_at,
            )
        )
    return articles


def fetch_category_articles(
    category: NewsCategory,
    settings: Settings,
) -> List[Article]:
    """
    카테고리에 속한 모든 검색어의 기사를 모아서
    - 최근 N시간 이내 기사만 필터링
    - 링크 기준 중복 제거
    - 최신순 정렬
    - max_items개로 제한
    """
    seen_links = set()
    collected: List[Article] = []

    for query in category.queries:
        try:
            articles = _fetch_query(query, settings)
        except Exception:
            logger.exception("뉴스 수집 실패 (query=%s), 해당 검색어는 건너뜁니다.", query)
            continue

        for article in articles:
            if article.dedup_key() in seen_links:
                continue
            seen_links.add(article.dedup_key())
            collected.append(article)

    if settings.max_article_age_hours > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.max_article_age_hours)
        collected = [a for a in collected if a.published_at >= cutoff]

    collected.sort(key=lambda a: a.published_at, reverse=True)
    return collected[: category.max_items]


def fetch_all_categories(settings: Settings) -> "dict[str, List[Article]]":
    """모든 카테고리에 대해 뉴스를 수집합니다. 하나가 실패해도 나머지는 계속 진행합니다."""
    result = {}
    for category in CATEGORIES:
        logger.info("뉴스 수집 시작: %s", category.label)
        result[category.key] = fetch_category_articles(category, settings)
        logger.info("뉴스 수집 완료: %s (%d건)", category.label, len(result[category.key]))
    return result
