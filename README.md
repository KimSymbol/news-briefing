# 📰 자동 뉴스 브리핑 봇

매일 아침 7시(KST) 뉴스를 수집 → AI 요약 → 디스코드로 전송하는 자동화 파이프라인

## 구조

```
GitHub Actions (cron: 매일 KST 07:00)
  ├─ RSS + NewsAPI → 뉴스 수집
  ├─ Gemini API → 요약 브리핑 생성
  └─ Discord Webhook → 채널에 전송
```

## 셋업 가이드

### 1. GitHub 저장소 생성

1. https://github.com/new 에서 새 저장소 생성
2. 저장소 이름: `news-briefing` (원하는 이름)
3. **Public** 선택 (GitHub Actions 무료 사용을 위해)
4. 이 프로젝트 파일들을 push

### 2. GitHub Secrets 등록

저장소 → Settings → Secrets and variables → Actions → New repository secret

| Secret 이름 | 값 |
|---|---|
| `DISCORD_WEBHOOK_URL` | 디스코드 웹훅 URL |
| `GEMINI_API_KEY` | Google Gemini API 키 |
| `NEWSAPI_KEY` | NewsAPI 키 |

### 3. 테스트 실행

저장소 → Actions 탭 → "Daily News Briefing" → Run workflow → Run

### 4. 완료

매일 아침 7시에 디스코드 채널에 뉴스 브리핑이 도착합니다.

## 커스터마이징

- **시간 변경**: `.github/workflows/daily_news.yml`의 cron 수정 (UTC 기준)
- **RSS 추가**: `news_briefing.py`의 `rss_feeds` 리스트에 추가
- **카테고리 변경**: Gemini 프롬프트 수정
