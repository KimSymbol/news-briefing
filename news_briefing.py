"""
매일 아침 뉴스 브리핑 자동화
RSS + NewsAPI → Gemini 요약 → Discord Webhook 전송
"""

import os
import json
import re
import feedparser
import requests
from datetime import datetime, timedelta, timezone
from google import genai

# ─── 환경변수 ───
DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
NEWSAPI_KEY = os.environ["NEWSAPI_KEY"]

# ─── 시간 설정 ───
KST = timezone(timedelta(hours=9))
NOW_KST = datetime.now(KST)
YESTERDAY = NOW_KST - timedelta(hours=24)


# ─── 1. 뉴스 수집 ───

def fetch_rss(url: str, label: str) -> list[dict]:
    """RSS 피드에서 최근 24시간 기사 수집"""
    articles = []
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:20]:
            # 발행 시간 파싱
            published = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                published = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)

            # 24시간 필터 (시간 정보 없으면 포함)
            if published and published < YESTERDAY.astimezone(timezone.utc):
                continue

            articles.append({
                "title": entry.get("title", "제목 없음"),
                "link": entry.get("link", ""),
                "summary": entry.get("summary", "")[:300],
                "source": label,
                "published": str(published) if published else "시간 불명",
            })
    except Exception as e:
        print(f"[RSS 오류] {label}: {e}")
    return articles


def fetch_newsapi(category: str = None, country: str = "kr", query: str = None) -> list[dict]:
    """NewsAPI에서 헤드라인 수집"""
    articles = []
    try:
        params = {
            "apiKey": NEWSAPI_KEY,
            "pageSize": 15,
        }
        if query:
            # everything 엔드포인트
            url = "https://newsapi.org/v2/everything"
            params["q"] = query
            params["from"] = YESTERDAY.strftime("%Y-%m-%d")
            params["sortBy"] = "relevancy"
            params["language"] = "ko"
        else:
            # top-headlines 엔드포인트
            url = "https://newsapi.org/v2/top-headlines"
            params["country"] = country
            if category:
                params["category"] = category

        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()

        for item in data.get("articles", []):
            articles.append({
                "title": item.get("title", ""),
                "link": item.get("url", ""),
                "summary": (item.get("description") or "")[:300],
                "source": item.get("source", {}).get("name", "NewsAPI"),
                "published": item.get("publishedAt", ""),
            })
    except Exception as e:
        print(f"[NewsAPI 오류] {category or query}: {e}")
    return articles


def collect_all_news() -> dict:
    """모든 소스에서 뉴스 수집"""

    # RSS 피드 목록
    rss_feeds = [
        ("https://www.yonhapnewstv.co.kr/browse/feed/", "연합뉴스TV"),
        ("https://feeds.feedburner.com/haborymag", "GeekNews"),
        ("https://www.gamesindustry.biz/feed", "GamesIndustry.biz"),
        ("https://www.gamedeveloper.com/rss.xml", "Game Developer"),
        ("https://techcrunch.com/feed/", "TechCrunch"),
        ("https://feeds.arstechnica.com/arstechnica/technology-lab", "Ars Technica"),
    ]

    news = {
        "종합": [],
        "기술_AI": [],
        "게임": [],
        "경제": [],
    }

    # RSS 수집
    for url, label in rss_feeds:
        articles = fetch_rss(url, label)
        if label in ("GeekNews", "TechCrunch", "Ars Technica"):
            news["기술_AI"].extend(articles)
        elif label in ("GamesIndustry.biz", "Game Developer"):
            news["게임"].extend(articles)
        else:
            news["종합"].extend(articles)

    # NewsAPI 수집
    news["종합"].extend(fetch_newsapi(country="kr"))
    news["종합"].extend(fetch_newsapi(country="us"))
    news["경제"].extend(fetch_newsapi(category="business", country="kr"))
    news["기술_AI"].extend(fetch_newsapi(category="technology"))
    news["기술_AI"].extend(fetch_newsapi(query="AI OR artificial intelligence OR OpenAI OR NVIDIA"))
    news["게임"].extend(fetch_newsapi(query="게임 OR game release OR Steam OR PlayStation OR Nintendo"))

    # 중복 제거 (제목 유사도 기준)
    for key in news:
        seen_titles = set()
        unique = []
        for article in news[key]:
            title_clean = re.sub(r"[^가-힣a-zA-Z0-9]", "", article["title"].lower())
            if title_clean not in seen_titles and len(title_clean) > 5:
                seen_titles.add(title_clean)
                unique.append(article)
        news[key] = unique

    return news


# ─── 2. AI 요약 ───

def summarize_with_gemini(news: dict) -> str:
    """Gemini API로 뉴스 브리핑 생성"""

    # 수집된 뉴스를 텍스트로 변환
    news_text = ""
    for category, articles in news.items():
        news_text += f"\n\n=== {category} ({len(articles)}건) ===\n"
        for a in articles:
            news_text += f"- [{a['source']}] {a['title']}\n  요약: {a['summary']}\n  링크: {a['link']}\n  시간: {a['published']}\n"

    today_str = NOW_KST.strftime("%Y년 %m월 %d일 (%A)")

    prompt = f"""당신은 뉴스 브리핑 에디터입니다.
아래 수집된 뉴스 원문을 분석하여 한글 브리핑을 작성하세요.

## 작성 규칙
- 수집된 뉴스에 없는 내용은 절대 쓰지 마세요
- 루머/추측 제외, 사실만 포함
- 중복 기사는 하나로 통합
- 중요도가 높은 순서로 정렬
- 핵심 수치 포함
- 각 기사에 출처와 링크 표기
- 해당 분야에 중요 뉴스가 없으면 "특이사항 없음"으로 표기

## 출력 형식

📅 **오늘의 브리핑 — {today_str}**

---

🔥 **핵심 헤드라인 TOP 5**
(분야 불문 가장 중요한 뉴스 5개, 각각 한줄요약 + 왜 중요한가 + 출처/링크)

---

🤖 **AI · IT · 기술**
(주요 뉴스, 각각 3줄 요약 + 영향 + 출처/링크)

---

🎮 **게임 업계**
(주요 뉴스, 각각 요약 + 게이머/업계 영향 + 출처/링크)

---

💰 **경제 · 금융**
(증시/환율 포함, 주요 뉴스 요약 + 출처/링크)

---

🎯 **관심 분야 (게임 QA · 자동화 테스트 · AI 활용)**
(관련 뉴스가 있으면 정리, 없으면 "특이사항 없음")

---

✍️ **오늘 꼭 알아야 할 한 문장**

## 수집된 뉴스 원문
{news_text}
"""

    # 무료 모델 우선순위 — Google이 변경해도 다음 모델로 자동 시도
    MODELS = [
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-1.5-flash",
    ]

    client = genai.Client(api_key=GEMINI_API_KEY)

    for model_name in MODELS:
        try:
            print(f"  모델 시도: {model_name}")
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            print(f"  ✅ 성공: {model_name}")
            return response.text
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                print(f"  ❌ {model_name}: 할당량 초과, 다음 모델 시도...")
                continue
            else:
                raise

    raise RuntimeError("모든 Gemini 모델이 할당량 초과 상태입니다.")


# ─── 3. 디스코드 전송 ───

def send_to_discord(content: str):
    """디스코드 웹훅으로 메시지 전송 (2000자 분할)"""

    # 섹션 단위로 분할 (--- 기준)
    sections = content.split("\n---\n")
    chunks = []
    current_chunk = ""

    for section in sections:
        # 섹션 추가 시 2000자 초과하면 현재 청크 저장 후 새 청크
        test = current_chunk + "\n---\n" + section if current_chunk else section
        if len(test) > 1900:
            if current_chunk:
                chunks.append(current_chunk)
            # 섹션 자체가 1900자 넘으면 추가 분할
            if len(section) > 1900:
                for i in range(0, len(section), 1900):
                    chunks.append(section[i:i + 1900])
            else:
                current_chunk = section
        else:
            current_chunk = test

    if current_chunk:
        chunks.append(current_chunk)

    # 전송
    for i, chunk in enumerate(chunks):
        payload = {"content": chunk}
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
        if resp.status_code == 204:
            print(f"[Discord] 청크 {i + 1}/{len(chunks)} 전송 성공")
        elif resp.status_code == 429:
            # Rate limit 대기
            import time
            retry_after = resp.json().get("retry_after", 2)
            print(f"[Discord] Rate limited, {retry_after}초 대기")
            time.sleep(retry_after)
            requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
        else:
            print(f"[Discord] 전송 실패: {resp.status_code} {resp.text}")


# ─── 메인 실행 ───

def main():
    print(f"=== 뉴스 브리핑 시작: {NOW_KST.strftime('%Y-%m-%d %H:%M KST')} ===")

    # 1단계: 뉴스 수집
    print("\n[1/3] 뉴스 수집 중...")
    news = collect_all_news()
    total = sum(len(v) for v in news.values())
    print(f"  수집 완료: 총 {total}건")
    for cat, articles in news.items():
        print(f"  - {cat}: {len(articles)}건")

    if total == 0:
        print("수집된 뉴스가 없습니다. 종료합니다.")
        send_to_discord("⚠️ 오늘은 수집된 뉴스가 없습니다. RSS/API 상태를 확인해 주세요.")
        return

    # 2단계: AI 요약
    print("\n[2/3] Gemini로 브리핑 생성 중...")
    briefing = summarize_with_gemini(news)
    print(f"  브리핑 생성 완료: {len(briefing)}자")

    # 3단계: 디스코드 전송
    print("\n[3/3] 디스코드 전송 중...")
    send_to_discord(briefing)

    print("\n=== 완료 ===")


if __name__ == "__main__":
    main()
