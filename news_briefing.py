"""
매일 아침 뉴스 브리핑 자동화
RSS + NewsAPI → Gemini 요약 → Discord Webhook 전송
"""

import os
import re
import time
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


# ═══════════════════════════════════════
# 1. 뉴스 수집
# ═══════════════════════════════════════

def fetch_rss(url: str, label: str) -> list[dict]:
    """RSS 피드에서 최근 24시간 기사 수집"""
    articles = []
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:20]:
            published = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                published = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)

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
        print(f"  [RSS 오류] {label}: {e}")
    return articles


def fetch_newsapi(category: str = None, country: str = "kr", query: str = None) -> list[dict]:
    """NewsAPI에서 헤드라인 수집"""
    articles = []
    try:
        params = {"apiKey": NEWSAPI_KEY, "pageSize": 15}
        if query:
            url = "https://newsapi.org/v2/everything"
            params["q"] = query
            params["from"] = YESTERDAY.strftime("%Y-%m-%d")
            params["sortBy"] = "relevancy"
            params["language"] = "ko"
        else:
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
        print(f"  [NewsAPI 오류] {category or query}: {e}")
    return articles


def collect_all_news() -> dict:
    """모든 소스에서 뉴스 수집"""

    rss_feeds = [
        # 한국 종합
        ("https://www.yonhapnewstv.co.kr/browse/feed/", "연합뉴스TV"),
        # 기술/AI
        ("https://feeds.feedburner.com/haborymag", "GeekNews"),
        ("https://techcrunch.com/feed/", "TechCrunch"),
        ("https://feeds.arstechnica.com/arstechnica/technology-lab", "Ars Technica"),
        # 게임
        ("https://www.gamesindustry.biz/feed", "GamesIndustry.biz"),
        ("https://www.gamedeveloper.com/rss.xml", "Game Developer"),
        ("https://www.gamemeca.com/rss.xml", "게임메카"),
        ("https://www.inven.co.kr/webzine/rss.php", "인벤"),
        ("https://store.steampowered.com/feeds/newreleases.xml", "Steam New Releases"),
    ]

    news = {
        "한국_종합": [],
        "글로벌_종합": [],
        "기술_AI": [],
        "게임": [],
        "경제": [],
    }

    # RSS 수집
    for url, label in rss_feeds:
        articles = fetch_rss(url, label)
        if label in ("GeekNews", "TechCrunch", "Ars Technica"):
            news["기술_AI"].extend(articles)
        elif label in ("GamesIndustry.biz", "Game Developer", "게임메카", "인벤", "Steam New Releases"):
            news["게임"].extend(articles)
        elif label == "연합뉴스TV":
            news["한국_종합"].extend(articles)
        else:
            news["글로벌_종합"].extend(articles)

    # NewsAPI 수집
    news["한국_종합"].extend(fetch_newsapi(country="kr"))
    news["글로벌_종합"].extend(fetch_newsapi(country="us"))
    news["경제"].extend(fetch_newsapi(category="business", country="kr"))
    news["경제"].extend(fetch_newsapi(category="business", country="us"))
    news["기술_AI"].extend(fetch_newsapi(category="technology"))
    news["기술_AI"].extend(fetch_newsapi(query="AI OR OpenAI OR NVIDIA OR Anthropic OR Google AI"))
    news["게임"].extend(fetch_newsapi(query="게임 출시 OR 게임 업데이트 OR e스포츠"))
    news["게임"].extend(fetch_newsapi(query="game release OR Steam OR PlayStation OR Nintendo OR Xbox", country="us"))

    # 중복 제거
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


# ═══════════════════════════════════════
# 2. AI 요약
# ═══════════════════════════════════════

def summarize_with_gemini(news: dict) -> str:
    """Gemini API로 뉴스 브리핑 생성"""

    # 수집된 뉴스를 텍스트로 변환
    news_text = ""
    for category, articles in news.items():
        news_text += f"\n\n=== [{category}] 수집 {len(articles)}건 ===\n"
        for i, a in enumerate(articles, 1):
            news_text += (
                f"{i}. [{a['source']}] {a['title']}\n"
                f"   요약: {a['summary']}\n"
                f"   링크: {a['link']}\n"
                f"   시간: {a['published']}\n\n"
            )

    today_str = NOW_KST.strftime("%Y년 %m월 %d일 (%A)")

    prompt = f"""당신은 뉴스 브리핑 에디터입니다.
아래 "수집된 뉴스 원문"만을 사용하여 한글 브리핑을 작성하세요.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ 절대 금지 규칙 (반드시 준수)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 수집된 원문에 없는 고유명사(인명, 회사명, 제품명, 모델명)를 절대 생성하지 마세요.
2. 수집된 원문에 없는 수치, 통계, 금액을 절대 생성하지 마세요.
3. 원문의 고유명사를 그대로 사용하세요. 변형·번역·추측하지 마세요.
4. 확실하지 않은 정보는 포함하지 말고 "확인 필요"로 표기하세요.
5. 원문에 링크가 있으면 반드시 포함하세요. 링크를 추측하여 생성하지 마세요.
6. 중복 기사는 하나로 통합하세요. 동일 뉴스를 여러 섹션에 반복하지 마세요.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 출력 형식 (디스코드 전송용 — 이 형식을 정확히 따르세요)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

각 섹션을 아래 구분자로 나누세요: $$SECTION$$

섹션 1:
📅 **오늘의 브리핑 — {today_str}**

🔥 **핵심 헤드라인 TOP 5**
(분야·국가 불문 가장 중요한 뉴스 5개)
각 항목:
> **제목**
> 한줄 요약 | 왜 중요한가
> 출처: 매체명 — 링크

$$SECTION$$

섹션 2:
🇰🇷 **한국 주요 뉴스**
(국내 주요 뉴스 3~7개, 없으면 "특이사항 없음")
각 항목:
**제목**
• 핵심 내용 2~3줄
• 영향
• 출처: 매체명 — 링크

$$SECTION$$

섹션 3:
🌍 **글로벌 주요 뉴스**
(해외 주요 뉴스 3~7개, 없으면 "특이사항 없음")
각 항목: 위와 동일 형식

$$SECTION$$

섹션 4:
🤖 **AI · IT · 기술**
(주요 뉴스 3~7개, 없으면 "특이사항 없음")
각 항목: 위와 동일 형식

$$SECTION$$

섹션 5:
🎮 **게임 업계**
(주요 뉴스 3~7개, 없으면 "특이사항 없음")
각 항목: 위와 동일 형식

$$SECTION$$

섹션 6:
💰 **경제 · 금융**
(증시/환율 수치 포함, 3~5개, 없으면 "특이사항 없음")
각 항목: 위와 동일 형식

$$SECTION$$

섹션 7:
🎯 **관심 분야** (게임 QA · 자동화 테스트 · AI 활용)
(관련 뉴스가 있으면 정리, 없으면 "특이사항 없음")

✍️ **오늘 꼭 알아야 할 한 문장**
(전체 뉴스를 한 문장으로 요약)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
수집된 뉴스 원문
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{news_text}
"""

    # 무료 모델 우선순위
    MODELS = [
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-1.5-flash",
    ]

    client = genai.Client(api_key=GEMINI_API_KEY)
    RETRYABLE = ["429", "503", "500", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "INTERNAL"]

    for model_name in MODELS:
        for attempt in range(2):
            try:
                print(f"  모델 시도: {model_name} (시도 {attempt + 1}/2)")
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                print(f"  ✅ 성공: {model_name}")
                return response.text
            except Exception as e:
                error_msg = str(e)
                is_retryable = any(code in error_msg for code in RETRYABLE)
                if is_retryable and attempt == 0:
                    print(f"  ⏳ {model_name}: 일시적 오류, 20초 후 재시도...")
                    time.sleep(20)
                    continue
                elif is_retryable:
                    print(f"  ❌ {model_name}: 실패, 다음 모델로...")
                    break
                else:
                    raise

    raise RuntimeError("모든 Gemini 모델 시도 실패. API 상태를 확인하세요.")


# ═══════════════════════════════════════
# 3. 디스코드 전송
# ═══════════════════════════════════════

def send_to_discord(content: str):
    """디스코드 웹훅으로 섹션 단위 전송 (중복 방지)"""

    # $$SECTION$$ 구분자로 분할 (Gemini 프롬프트에서 지정)
    sections = [s.strip() for s in content.split("$$SECTION$$") if s.strip()]

    # 구분자가 없으면 폴백: 이모지 헤더 기준으로 분할
    if len(sections) <= 1:
        split_markers = ["🇰🇷", "🌍", "🤖", "🎮", "💰", "🎯"]
        sections = []
        remaining = content
        for marker in split_markers:
            if marker in remaining:
                idx = remaining.index(marker)
                before = remaining[:idx].strip()
                if before:
                    sections.append(before)
                remaining = remaining[idx:]
        if remaining.strip():
            sections.append(remaining.strip())

    # 각 섹션을 2000자 이내로 전송
    sent_count = 0
    for section in sections:
        # 섹션이 1900자 넘으면 줄바꿈 기준으로 분할
        if len(section) > 1900:
            lines = section.split("\n")
            chunk = ""
            for line in lines:
                if len(chunk) + len(line) + 1 > 1900:
                    if chunk:
                        _post_discord(chunk, sent_count)
                        sent_count += 1
                    chunk = line
                else:
                    chunk = chunk + "\n" + line if chunk else line
            if chunk:
                _post_discord(chunk, sent_count)
                sent_count += 1
        else:
            _post_discord(section, sent_count)
            sent_count += 1

    print(f"  총 {sent_count}개 메시지 전송 완료")


def _post_discord(text: str, index: int):
    """단일 디스코드 메시지 전송"""
    payload = {"content": text}
    resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)

    if resp.status_code == 204:
        print(f"  [Discord] 메시지 {index + 1} 전송 성공 ({len(text)}자)")
    elif resp.status_code == 429:
        retry_after = resp.json().get("retry_after", 3)
        print(f"  [Discord] Rate limited, {retry_after}초 대기...")
        time.sleep(retry_after + 0.5)
        requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
    else:
        print(f"  [Discord] 전송 실패: {resp.status_code} {resp.text}")

    # 연속 전송 시 rate limit 방지
    time.sleep(1)


# ═══════════════════════════════════════
# 메인 실행
# ═══════════════════════════════════════

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
