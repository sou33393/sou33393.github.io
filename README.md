# Daily News Briefing → 카카오톡 자동 발송

매일 아침 AI/기술, 경제/금융, 정책/사회 뉴스를 자동으로 수집해
카카오톡(나에게 보내기)으로 전송하는 자동화 시스템입니다.

GitHub Actions에서 실행되므로 **본인 컴퓨터를 켜둘 필요가 없습니다.**

---

## 아키텍처

```
GitHub Actions (매일 08:00 KST)
   └─ src/main.py
        ├─ news_service.py    → 네이버 뉴스 검색 API로 카테고리별 기사 수집
        ├─ formatter.py       → 기사 목록을 카테고리별로 정리
        ├─ page_builder.py    → 기사 목록을 브리핑 웹페이지(docs/index.html)로 생성
        ├─ kakao_token_manager.py → 액세스 토큰 자동 갱신
        └─ kakao_client.py    → 카카오 '나에게 보내기' API로 페이지 링크 알림 발송
```

- **재시도 로직**: 모든 외부 API 호출은 지수 백오프로 최대 3회 재시도 (`http_utils.py`)
- **부분 실패 허용**: 한 카테고리/검색어 수집이 실패해도 나머지는 계속 진행
- **토큰 자동 갱신**: 액세스 토큰 만료 5분 전에 자동으로 갱신 후 캐싱
- **왜 웹페이지를 거치는가**: 카카오톡 메시지의 링크 버튼은 [제품 링크 관리]에
  사전 등록된 도메인으로만 이동할 수 있어, 매일 바뀌는 언론사 도메인을 직접
  담을 수 없습니다. 대신 우리가 소유한 도메인(GitHub Pages) 하나만 등록해두고,
  실제 기사 목록/링크는 그 페이지 안의 일반 링크로 제공합니다.

---

## 1. 사전 준비: API 키 발급

### 네이버 검색 API (뉴스 수집용, 무료)
1. https://developers.naver.com/apps/#/register 접속
2. 애플리케이션 등록 → 사용 API에서 **검색** 체크
3. 발급된 **Client ID / Client Secret** 복사

### 카카오 API (메시지 발송용, 무료)
1. https://developers.kakao.com → 애플리케이션 추가
2. **앱 키 → REST API 키** 복사
3. **카카오 로그인** 활성화 + **동의항목**에서 "카카오톡 메시지 전송" 동의 설정
4. **플랫폼 → Web** 에 리다이렉트용 도메인 등록 (예: `https://localhost:3000`)
5. **카카오 로그인 → Redirect URI** 등록
6. 아래 URL을 브라우저로 접속해 로그인 후, 리다이렉트된 주소의 `code=` 값 확보:
   ```
   https://kauth.kakao.com/oauth/authorize?client_id={REST_API_키}&redirect_uri={Redirect_URI}&response_type=code&scope=talk_message
   ```
7. 발급받은 code로 토큰 교환:
   ```bash
   curl -X POST "https://kauth.kakao.com/oauth/token" \
     -d "grant_type=authorization_code" \
     -d "client_id={REST_API_키}" \
     -d "redirect_uri={Redirect_URI}" \
     -d "code={받은_인가코드}"
   ```
8. 응답에서 `refresh_token` 값을 확보 (이후 계속 사용)

---

## 2. 로컬 테스트

```bash
git clone <이 저장소>
cd daily-briefing
pip install -r requirements.txt
cp .env.example .env
# .env 파일을 열어서 발급받은 키 4개 입력

python src/main.py
```

성공하면 `docs/index.html`이 생성되고, 카카오톡에 브리핑 페이지 링크가 담긴
알림 메시지가 도착합니다. (로컬 실행 시에는 아직 실제 GitHub Pages 주소를
모르므로 링크 버튼이 임시값일 수 있습니다 — 정상입니다.)

---

## 3. GitHub Actions로 자동화 (컴퓨터 없이 매일 실행)

1. 이 프로젝트를 본인 GitHub 저장소에 push
2. 저장소 **Settings → Secrets and variables → Actions** 이동
3. 아래 4개 Secret 등록:
   - `NAVER_CLIENT_ID`
   - `NAVER_CLIENT_SECRET`
   - `KAKAO_REST_API_KEY`
   - `KAKAO_REFRESH_TOKEN`
4. **GitHub Pages 활성화** (브리핑 페이지 호스팅용):
   - 저장소 **Settings → Pages** 이동
   - **Source**: `Deploy from a branch` 선택
   - **Branch**: `main` / 폴더 `/docs` 선택 후 저장
   - 첫 워크플로우 실행 후 `https://<본인아이디>.github.io/<저장소이름>/` 로 페이지가 공개됩니다
   - 저장소가 Public이든 Private이든, 이 페이지 자체는 URL을 아는 사람에게는 공개됩니다
5. **카카오 링크 도메인 등록** (메시지의 "브리핑 보기" 버튼이 동작하려면 필요):
   - https://developers.kakao.com → 내 애플리케이션 → 앱 → **제품 링크 관리**
   - 웹 도메인에 `https://<본인아이디>.github.io` 등록
6. `.github/workflows/daily-briefing.yml` 이 매일 08:00 KST에 자동 실행되며,
   기사 수집 → 페이지 생성/커밋·푸시 → 카카오 알림 발송까지 자동으로 처리합니다.
7. **Actions 탭 → Daily News Briefing → Run workflow** 로 즉시 테스트 가능

---

## 4. 커스터마이징

### 카테고리/검색어 변경
`src/config.py`의 `CATEGORIES` 리스트를 수정하세요.

```python
NewsCategory(
    key="ai_tech",
    label="🤖 AI/기술",
    queries=["생성형 AI", "AI 신규 모델 출시", "AI 반도체"],
    max_items=3,
),
```

### 발송 시간 변경
`.github/workflows/daily-briefing.yml`의 cron 표현식 수정 (UTC 기준):
```yaml
- cron: "0 23 * * *"   # UTC 23:00 = KST 08:00
```

### 뉴스 소스 교체
`news_service.py`는 네이버 검색 API 전용으로 작성되어 있습니다.
다른 소스(RSS, NewsAPI 등)로 교체하려면 `fetch_category_articles` 함수의
반환 타입(`List[Article]`)만 맞추면 나머지 코드는 수정 없이 동작합니다.

---

## 5. 운영/상용화 시 고려사항

- **네이버 API 일일 호출 한도**: 기본 25,000회/일 (카테고리 3개 × 검색어 3개 = 9회/일 실행이므로 충분)
- **카카오 refresh_token 만료**: 정책상 일정 기간 미사용 시 만료될 수 있음 → 위 6번 과정으로 재발급
- **다중 사용자 지원으로 확장 시**: 현재는 1인 전용("나에게 보내기") 구조이므로,
  여러 사용자에게 발송하려면 카카오 비즈니스 채널 + 알림톡/친구톡 API로 전환 필요
  (알림톡은 사전 심사 및 발신 비용 발생)
- **모니터링**: GitHub Actions 실행 실패 시 저장소 Actions 탭에서 알림 확인,
  또는 Slack/이메일 알림 연동 가능
- **비밀 정보 관리**: `.env`, `.kakao_tokens.json`은 절대 git에 커밋하지 않도록 `.gitignore`에 포함됨

---

## 라이선스
개인/내부 용도로 자유롭게 사용 및 수정 가능합니다.
