"""
카카오톡 "나에게 보내기" API 클라이언트
"""
import json
import logging
from typing import Optional

from config import Settings
from http_utils import request_with_retry
from kakao_token_manager import KakaoTokenManager

logger = logging.getLogger(__name__)

KAKAO_MEMO_SEND_ENDPOINT = "https://kapi.kakao.com/v2/api/talk/memo/default/send"

_FALLBACK_LINK = {
    "web_url": "https://www.google.com/search?q=오늘의+뉴스",
    "mobile_web_url": "https://www.google.com/search?q=오늘의+뉴스",
}

# 카카오 text 템플릿 text 필드의 실제 최대 글자수 (공식 문서 기준, 카카오디벨로퍼스 message-template/default)
_TEXT_MAX_LENGTH = 200


def send_text_message(
    text: str,
    settings: Settings,
    token_manager: KakaoTokenManager,
    link_url: Optional[str] = None,
    button_title: str = "브리핑 보기",
) -> None:
    """
    텍스트 메시지를 '나에게 보내기'로 전송합니다 (API 제한: 최대 200자).

    link_url이 주어지면 메시지의 버튼이 그 URL로 이동합니다. 단, 카카오는
    [제품 링크 관리]에 등록된 도메인으로만 이동을 허용하므로, link_url의
    도메인이 사전 등록돼 있어야 버튼이 정상 동작합니다.
    """
    if len(text) > _TEXT_MAX_LENGTH:
        text = text[: _TEXT_MAX_LENGTH - 3] + "..."

    link = {"web_url": link_url, "mobile_web_url": link_url} if link_url else _FALLBACK_LINK

    template_object = {
        "object_type": "text",
        "text": text,
        "link": link,
        "button_title": button_title,
    }

    access_token = token_manager.get_valid_access_token()
    response = request_with_retry(
        "POST",
        KAKAO_MEMO_SEND_ENDPOINT,
        headers={"Authorization": f"Bearer {access_token}"},
        data={"template_object": json.dumps(template_object, ensure_ascii=False)},
        timeout=settings.request_timeout,
        max_retries=settings.max_retries,
    )

    result = response.json()
    if result.get("result_code") != 0:
        raise RuntimeError(f"카카오 메시지 전송 실패: {result}")

    logger.info("카카오톡 메시지 전송 성공")
