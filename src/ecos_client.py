"""
한국은행 ECOS API 클라이언트

코스피/코스닥/원달러 환율의 최신 값과 직전 영업일 대비 변동률을 가져옵니다.
ECOS는 호출 제한이 있으므로 하루 1회만 호출하고, 같은 날 재실행 시에는
로컬 캐시 파일(ecos_cache_path)을 재사용합니다.
"""
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

from config import Settings
from http_utils import request_with_retry

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")

_BASE_URL = "https://ecos.bok.or.kr/api/StatisticSearch"

# ECOS StatisticTableList/StatisticItemList API로 직접 검증한 코드 (추측 아님, 2026-07 확인)
#   802Y001 "주식시세(장)" → 0001000 코스피지수, 0089000 코스닥지수
#   731Y001 "주요국 통화의 대원화환율" → 0000001 원/미국달러(매매기준율)
#   722Y001 "한국은행 기준금리 및 여수신금리" → 0101000 한국은행 기준금리
_KOSPI = ("코스피", "802Y001", "0001000")
_KOSDAQ = ("코스닥", "802Y001", "0089000")
_USD_KRW = ("원/달러 환율", "731Y001", "0000001")
_BASE_RATE = ("기준금리", "722Y001", "0101000")

_LOOKBACK_DAYS = 10  # 공휴일/주말을 감안해 직전 영업일 값을 확보하기 위한 조회 기간


@dataclass
class Indicator:
    label: str
    value: float
    change_pct: Optional[float]  # 직전 영업일 대비 변동률(%). 비교 데이터가 없으면 None
    as_of: str  # YYYYMMDD


@dataclass
class EcosSnapshot:
    kospi: Indicator
    kosdaq: Indicator
    usd_krw: Indicator
    base_rate: Indicator


def _fetch_series(settings: Settings, stat_code: str, item_code: str) -> List[Tuple[str, float]]:
    """지정된 통계표/항목의 최근 시계열을 (날짜, 값) 리스트로 반환합니다 (날짜순 정렬)."""
    end = datetime.now(KST)
    start = end - timedelta(days=_LOOKBACK_DAYS)
    url = (
        f"{_BASE_URL}/{settings.ecos_api_key}/json/kr/1/{_LOOKBACK_DAYS}/"
        f"{stat_code}/D/{start.strftime('%Y%m%d')}/{end.strftime('%Y%m%d')}/{item_code}"
    )
    response = request_with_retry("GET", url, timeout=settings.request_timeout, max_retries=settings.max_retries)
    payload = response.json()

    result = payload.get("StatisticSearch")
    if not result or "row" not in result:
        error = payload.get("RESULT", {})
        raise RuntimeError(f"ECOS 응답에 데이터가 없습니다: {error or payload}")

    rows = [(row["TIME"], float(row["DATA_VALUE"])) for row in result["row"]]
    rows.sort(key=lambda r: r[0])
    return rows


def _to_indicator(label: str, rows: List[Tuple[str, float]]) -> Indicator:
    if not rows:
        raise RuntimeError(f"ECOS 시계열이 비어 있습니다: {label}")

    as_of, value = rows[-1]
    change_pct = None
    if len(rows) >= 2:
        _, previous = rows[-2]
        if previous:
            change_pct = round((value - previous) / previous * 100, 2)

    return Indicator(label=label, value=value, change_pct=change_pct, as_of=as_of)


def _fetch_snapshot(settings: Settings) -> EcosSnapshot:
    indicators = {}
    for label, stat_code, item_code in (_KOSPI, _KOSDAQ, _USD_KRW, _BASE_RATE):
        rows = _fetch_series(settings, stat_code, item_code)
        indicators[label] = _to_indicator(label, rows)

    return EcosSnapshot(
        kospi=indicators["코스피"],
        kosdaq=indicators["코스닥"],
        usd_krw=indicators["원/달러 환율"],
        base_rate=indicators["기준금리"],
    )


def _load_cache(cache_path: Path) -> Optional[dict]:
    if not cache_path.exists():
        return None
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, TypeError):
        logger.warning("ECOS 캐시 파일이 손상되어 무시합니다: %s", cache_path)
        return None


def _save_cache(cache_path: Path, date_str: str, snapshot: EcosSnapshot) -> None:
    data = {
        "date": date_str,
        "snapshot": {
            "kospi": asdict(snapshot.kospi),
            "kosdaq": asdict(snapshot.kosdaq),
            "usd_krw": asdict(snapshot.usd_krw),
            "base_rate": asdict(snapshot.base_rate),
        },
    }
    cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _snapshot_from_cache(data: dict) -> EcosSnapshot:
    snapshot = data["snapshot"]
    return EcosSnapshot(
        kospi=Indicator(**snapshot["kospi"]),
        kosdaq=Indicator(**snapshot["kosdaq"]),
        usd_krw=Indicator(**snapshot["usd_krw"]),
        base_rate=Indicator(**snapshot["base_rate"]),
    )


def get_daily_snapshot(settings: Settings) -> EcosSnapshot:
    """
    코스피/코스닥/원달러 환율의 최신 지표를 반환합니다.
    같은 날(KST) 캐시가 있으면 재사용하고, 없으면 ECOS API를 호출해 새로 캐싱합니다.
    """
    cache_path = Path(settings.ecos_cache_path)
    today = datetime.now(KST).strftime("%Y-%m-%d")

    cached = _load_cache(cache_path)
    if cached and cached.get("date") == today:
        logger.info("ECOS 캐시 재사용 (%s)", today)
        return _snapshot_from_cache(cached)

    logger.info("ECOS 최신 지표 조회 중...")
    snapshot = _fetch_snapshot(settings)
    _save_cache(cache_path, today, snapshot)
    return snapshot
