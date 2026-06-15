# 📰 자동 뉴스 브리핑 봇

매일 아침 뉴스를 수집 → AI 요약 → 디스코드로 전송하는 자동화 파이프라인

PC가 꺼져 있어도 GitHub Actions가 자동 실행합니다.

## 구조

```
GitHub Actions (cron: 매일 KST 07:00 설정, 지연 감안 08:00 전후 도착)
  ├─ RSS 11개 + NewsAPI 14개 쿼리 → 뉴스 수집 (카테고리별 최대 25건)
  ├─ yfinance → 코스피/코스닥/S&P500/나스닥/다우/환율 실시간 수치
  ├─ wttr.in → 오늘 날씨
  ├─ Gemini API (무료 tier, 3개 모델 자동 폴백) → AI 요약 브리핑 생성
  └─ Discord Webhook → 섹션별 분할 전송
```

## 브리핑 구조

```
📅 오늘의 브리핑 + 🌤️ 날씨
🔥 핵심 헤드라인 TOP 5
🇰🇷 한국 주요 뉴스
🌍 글로벌 주요 뉴스
🤖 AI · IT · 기술
🎮 게임 업계
⚽ 스포츠
💰 경제 · 금융 (📊 시장 요약 포함)
🎯 관심 분야 (게임 QA · 자동화 테스트)
✍️ 오늘 꼭 알아야 할 한 문장
📚 오늘의 용어
```

## 사용 기술

| 구성 요소 | 기술 | 비용 |
|---|---|---|
| 실행 환경 | GitHub Actions (cron) | 무료 (Public 저장소) |
| 뉴스 수집 | RSS (feedparser) + NewsAPI | 무료 |
| 시장 데이터 | yfinance (Yahoo Finance) | 무료, API 키 불필요 |
| 날씨 | wttr.in | 무료, API 키 불필요 |
| AI 요약 | Google Gemini API (무료 tier) | 무료 |
| 전송 | Discord Webhook | 무료 |

## 뉴스 소스

### RSS 피드
- **한국 종합**: 연합뉴스TV
- **글로벌 종합**: BBC World, NBC News World, NYT World
- **기술/AI**: TechCrunch, Ars Technica
- **게임**: GamesIndustry.biz, Game Developer, 게임메카, Steam New Releases
- **스포츠**: BBC Sport
- **경제**: 매일경제

### NewsAPI 쿼리
- 한국/미국 헤드라인, 비즈니스, 기술, 스포츠 카테고리
- 한국 증시 (코스피/코스닥/환율/증시 동향)
- 미국 증시 (S&P 500/Nasdaq/Dow Jones/Wall Street)
- 게임 (한국어 + 영어)
- AI/IT (OpenAI, NVIDIA, Anthropic 등)

## 셋업 가이드

### 1. 필요한 API 키 (2개만)

| 서비스 | 발급 URL |
|---|---|
| Google Gemini API | https://aistudio.google.com/apikey |
| NewsAPI | https://newsapi.org |

※ yfinance와 wttr.in은 API 키가 필요 없습니다.

### 2. Discord Webhook 만들기

1. 디스코드 서버에서 브리핑 받을 채널 → 채널 편집
2. 연동 → 웹후크 → 새 웹후크 → URL 복사

### 3. GitHub 저장소 생성 및 파일 업로드

```bash
git init
git add .
git commit -m "init: 뉴스 브리핑 자동화"
git branch -M main
git remote add origin https://github.com/[내계정]/news-briefing.git
git push -u origin main
```

※ **Public** 저장소로 만들어야 GitHub Actions 무료 사용 가능

### 4. GitHub Secrets 등록

저장소 → Settings → Secrets and variables → Actions → New repository secret

| Name | Value |
|---|---|
| `DISCORD_WEBHOOK_URL` | 디스코드 웹훅 URL |
| `GEMINI_API_KEY` | Gemini API 키 |
| `NEWSAPI_KEY` | NewsAPI 키 |

### 5. 테스트

저장소 → Actions 탭 → Daily News Briefing → Run workflow

## 커스터마이징

### 시간 변경
`.github/workflows/daily_news.yml`의 cron 수정 (UTC 기준)
```yaml
- cron: '0 22 * * *'  # KST 07:00
```

### 날씨 도시 변경
`news_briefing.py` 상단의 변수 수정
```python
WEATHER_CITY = "Daegu"  # Seoul, Busan 등으로 변경
```

### RSS 소스 추가/삭제
`news_briefing.py`의 `rss_feeds` 리스트와 라우팅 `set` 수정

### AI 모델 변경
`MODELS` 리스트에서 우선순위 변경 또는 다른 API로 교체 가능
현재: gemini-2.5-flash → gemini-2.5-flash-lite → gemini-2.5-pro

## 안전장치

- **Gemini 모델 폴백**: 3개 모델 자동 전환 (503/429 에러 시)
- **실패 알림**: 스크립트 에러 시 디스코드로 에러 메시지 전송
- **카테고리별 25건 제한**: 토큰 초과 방지
- **환각 방지**: 프롬프트에 "원문에 없는 고유명사/수치 생성 금지" 규칙
- **중복 방지**: 동일 뉴스 여러 섹션 반복 금지 규칙

## 참고사항

- GitHub Actions cron은 최대 15~60분 지연될 수 있습니다
- Gemini 무료 tier는 서버 과부하 시 503 에러가 발생할 수 있으나, 폴백 모델이 처리합니다
- 주말에는 한국 증시가 휴장이므로 금요일 종가가 표시됩니다
- RSS 소스 중 일부는 GitHub Actions IP를 차단(403)할 수 있으나, NewsAPI가 백업합니다
