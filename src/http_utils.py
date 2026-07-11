"""
HTTP 요청 재시도 유틸리티

네트워크 요청은 실패할 수 있으므로, 지수 백오프(exponential backoff) 방식으로
재시도하는 공통 래퍼를 제공합니다.
"""
import logging
import time
from typing import Any, Callable, Dict, Optional

import requests

logger = logging.getLogger(__name__)


class HttpError(Exception):
    """재시도를 모두 소진한 뒤 발생하는 최종 에러"""


def request_with_retry(
    method: str,
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    json: Optional[Dict[str, Any]] = None,
    timeout: int = 10,
    max_retries: int = 3,
    retry_on_status: tuple = (429, 500, 502, 503, 504),
) -> requests.Response:
    """
    HTTP 요청을 보내고, 실패 시 지수 백오프로 재시도합니다.

    Raises:
        HttpError: 모든 재시도가 실패했을 때
    """
    last_exception: Optional[Exception] = None

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                data=data,
                json=json,
                timeout=timeout,
            )

            if response.status_code in retry_on_status:
                logger.warning(
                    "요청 실패 (status=%s), 재시도 %s/%s: %s",
                    response.status_code, attempt, max_retries, url,
                )
                last_exception = HttpError(
                    f"HTTP {response.status_code}: {response.text[:200]}"
                )
                time.sleep(min(2 ** attempt, 30))
                continue

            response.raise_for_status()
            return response

        except requests.RequestException as exc:
            logger.warning(
                "요청 예외 발생, 재시도 %s/%s: %s (%s)",
                attempt, max_retries, url, exc,
            )
            last_exception = exc
            time.sleep(min(2 ** attempt, 30))

    raise HttpError(f"{max_retries}회 재시도 후 요청 실패: {url}") from last_exception
