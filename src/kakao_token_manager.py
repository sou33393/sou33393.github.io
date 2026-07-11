"""
카카오 액세스 토큰 관리 모듈

카카오 액세스 토큰은 발급 후 약 6시간 뒤 만료됩니다.
이 모듈은:
1. 로컬 캐시 파일(JSON)에서 토큰을 읽고
2. 만료됐거나 캐시가 없으면 refresh_token으로 자동 갱신하고
3. 갱신된 토큰(및 새 refresh_token, 있는 경우)을 다시 캐시에 저장합니다.

주의: refresh_token 자체도 카카오 정책상 갱신될 수 있으므로,
      운영 환경(GitHub Actions 등)에서는 매 실행 후 갱신된 refresh_token을
      Secrets에 다시 반영하는 절차를 권장합니다. (README 참고)
"""
import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from config import Settings
from http_utils import request_with_retry

logger = logging.getLogger(__name__)

KAKAO_TOKEN_ENDPOINT = "https://kauth.kakao.com/oauth/token"

# 만료 시각 도달 전 미리 갱신할 여유 시간(초)
_REFRESH_MARGIN_SECONDS = 300


@dataclass
class TokenBundle:
    access_token: str
    refresh_token: str
    expires_at: float  # UNIX timestamp

    def is_valid(self) -> bool:
        return time.time() < (self.expires_at - _REFRESH_MARGIN_SECONDS)


class KakaoTokenManager:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._cache_path = Path(settings.token_cache_path)

    def _load_cache(self) -> Optional[TokenBundle]:
        if not self._cache_path.exists():
            return None
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            return TokenBundle(**data)
        except (json.JSONDecodeError, TypeError, KeyError):
            logger.warning("토큰 캐시 파일이 손상되어 무시합니다: %s", self._cache_path)
            return None

    def _save_cache(self, bundle: TokenBundle) -> None:
        self._cache_path.write_text(
            json.dumps(asdict(bundle), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _refresh(self, refresh_token: str) -> TokenBundle:
        logger.info("카카오 액세스 토큰 갱신 중...")
        response = request_with_retry(
            "POST",
            KAKAO_TOKEN_ENDPOINT,
            data={
                "grant_type": "refresh_token",
                "client_id": self._settings.kakao_rest_api_key,
                "refresh_token": refresh_token,
            },
            timeout=self._settings.request_timeout,
            max_retries=self._settings.max_retries,
        )
        payload = response.json()

        new_access_token = payload["access_token"]
        # 카카오가 refresh_token을 새로 내려주지 않으면 기존 것 유지
        new_refresh_token = payload.get("refresh_token", refresh_token)
        expires_in = payload.get("expires_in", 21600)  # 기본 6시간

        bundle = TokenBundle(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            expires_at=time.time() + expires_in,
        )
        self._save_cache(bundle)

        if new_refresh_token != refresh_token:
            logger.warning(
                "refresh_token이 갱신되었습니다. "
                "운영 환경의 KAKAO_REFRESH_TOKEN Secret을 업데이트하세요."
            )
        return bundle

    def get_valid_access_token(self) -> str:
        """유효한 액세스 토큰을 반환합니다. 필요 시 자동 갱신합니다."""
        cached = self._load_cache()
        if cached and cached.is_valid():
            logger.debug("캐시된 유효한 토큰 사용")
            return cached.access_token

        refresh_token = cached.refresh_token if cached else self._settings.kakao_refresh_token
        bundle = self._refresh(refresh_token)
        return bundle.access_token
