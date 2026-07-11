"""
정부 부처 / 빅테크 공식 블로그 RSS 수집 모듈

정책브리핑(korea.kr) 통합 RSS는 서비스가 중단되어, 부처별 공식 도메인 RSS를
직접 사용합니다. 여러 정부 사이트가 표준을 벗어난 날짜 형식을 쓰므로
날짜 파싱은 여러 포맷을 순차 시도합니다.
"""
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

from config import Settings
from http_utils import request_with_retry

logger = logging.getLogger(__name__)

_DC_NS = {"dc": "http://purl.org/dc/elements/1.1/"}

# dc:date / 비표준 pubDate에서 시도할 날짜 포맷들
_FALLBACK_DATE_FORMATS = ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S")

# 부처 사이트의 비표준 날짜(dc:date, "YYYY-MM-DD HH:MM:SS")는 타임존 표기가 없지만
# 실제로는 한국 시간이므로 KST로 간주한다.
_KST_FALLBACK_TZ = ZoneInfo("Asia/Seoul")


@dataclass
class RssItem:
    title: str
    link: str
    published_at: datetime
    source_label: str


def _parse_date(text: str) -> Optional[datetime]:
    text = (text or "").strip()
    if not text:
        return None

    try:
        dt = parsedate_to_datetime(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        pass

    for fmt in _FALLBACK_DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=_KST_FALLBACK_TZ)
        except ValueError:
            continue

    return None


def fetch_rss(url: str, source_label: str, settings: Settings) -> List[RssItem]:
    """RSS 피드를 가져와 최신순으로 정렬된 항목 목록을 반환합니다."""
    response = request_with_retry("GET", url, timeout=settings.request_timeout, max_retries=settings.max_retries)
    root = ET.fromstring(response.content)

    items = []
    for item_el in root.iter("item"):
        title_el = item_el.find("title")
        link_el = item_el.find("link")
        if title_el is None or link_el is None or not (link_el.text or "").strip():
            continue

        pub_date_el = item_el.find("pubDate")
        published_at = _parse_date(pub_date_el.text) if pub_date_el is not None else None

        if published_at is None:
            dc_date_el = item_el.find("dc:date", _DC_NS)
            published_at = _parse_date(dc_date_el.text) if dc_date_el is not None else None

        if published_at is None:
            logger.debug("%s: 발행일 파싱 실패, 건너뜁니다 (%s)", source_label, (title_el.text or "").strip())
            continue

        items.append(
            RssItem(
                title=(title_el.text or "").strip(),
                link=link_el.text.strip(),
                published_at=published_at,
                source_label=source_label,
            )
        )

    items.sort(key=lambda i: i.published_at, reverse=True)
    return items


def _impact_score(item: RssItem, keywords: List[str]) -> int:
    return sum(1 for keyword in keywords if keyword in item.title)


def latest_within_window(
    sources: List[Tuple[str, str]],
    settings: Settings,
    impact_keywords: Optional[List[str]] = None,
    candidates_per_source: int = 3,
) -> Tuple[Optional[RssItem], List[str]]:
    """
    여러 RSS 소스에서 헤드라인 후보 하나를 고릅니다.

    impact_keywords가 주어지면 각 소스의 최근 항목(candidates_per_source개)까지
    모아 제목에 키워드가 가장 많이 매칭되는 항목을 우선 선택합니다(파급력 우선).
    없으면 단순 최신순으로 고릅니다. max_article_age_hours 기준을 벗어나면
    (=오늘 새 발표가 없으면) None을 반환해 호출부가 다른 소스로 폴백할 수 있게 합니다.

    반환값은 (선정된 항목 또는 None, 수집에 실패한 소스 라벨 목록) 입니다.
    """
    candidates: List[RssItem] = []
    failed_labels: List[str] = []

    for label, url in sources:
        try:
            items = fetch_rss(url, label, settings)
        except Exception:
            logger.exception("RSS 수집 실패, 건너뜁니다: %s (%s)", label, url)
            failed_labels.append(label)
            continue
        candidates.extend(items[:candidates_per_source] if impact_keywords else items[:1])

    if not candidates:
        return None, failed_labels

    if settings.max_article_age_hours > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.max_article_age_hours)
        candidates = [c for c in candidates if c.published_at >= cutoff]

    if not candidates:
        logger.info("오늘 새 발표가 없어 폴백합니다 (기준: %d시간).", settings.max_article_age_hours)
        return None, failed_labels

    if impact_keywords:
        candidates.sort(key=lambda i: (_impact_score(i, impact_keywords), i.published_at), reverse=True)
    else:
        candidates.sort(key=lambda i: i.published_at, reverse=True)

    return candidates[0], failed_labels
