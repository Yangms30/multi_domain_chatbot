"""
Auto Knowledge Collector - Streamlit UI

LLM Provider Priority:
    1. Ollama (local, free) - auto-detected
    2. OpenRouter API (cloud, paid) - fallback

Usage:
    cd backend
    streamlit run scripts/collector_app.py
"""

import json
import os
import re
import sys
import time
from datetime import datetime

import httpx
import streamlit as st
from dotenv import load_dotenv
from supabase import create_client

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

try:
    from web_scraper import WebScraper
    HAS_SCRAPER = True
except ImportError:
    try:
        from scripts.web_scraper import WebScraper
        HAS_SCRAPER = True
    except ImportError:
        HAS_SCRAPER = False

OLLAMA_BASE = "http://localhost:11434"

# ── Domain Schemas (self-contained, no external import) ──────────

DOMAIN_SCHEMAS = {
    "movie": {
        "category": "movie",
        "build_tags": lambda data: (
            data.get("genres", [])
            + [data.get("director", "")]
            + [c.get("name", "") for c in data.get("cast", [])[:5]]
            + [data.get("original_language", "")]
        ),
        "build_content": lambda data: (
            f"{data.get('title', '')} ({data.get('release_date', '')[:4] if data.get('release_date') else '미정'})\n"
            f"감독: {data.get('director', '')}\n"
            f"출연: {', '.join(c.get('name', '') for c in data.get('cast', [])[:5])}\n"
            f"장르: {', '.join(data.get('genres', []))}\n"
            f"평점: {data.get('vote_average', 0)}/10\n"
            f"줄거리: {data.get('overview', '')}"
        ),
    },
    "drama": {
        "category": "drama",
        "build_tags": lambda data: (
            data.get("genres", [])
            + [data.get("director", "")]
            + [data.get("writer", "")]
            + [c.get("name", "") for c in data.get("cast", [])[:5]]
            + [data.get("network", "")]
            + [data.get("original_language", "")]
        ),
        "build_content": lambda data: (
            f"{data.get('title', '')} ({data.get('air_date', '')[:4] if data.get('air_date') else '미정'})\n"
            f"연출: {data.get('director', '')}\n"
            f"작가: {data.get('writer', '')}\n"
            f"출연: {', '.join(c.get('name', '') for c in data.get('cast', [])[:5])}\n"
            f"장르: {', '.join(data.get('genres', []))}\n"
            f"방송사: {data.get('network', '')}\n"
            f"평점: {data.get('vote_average', 0)}/10\n"
            f"줄거리: {data.get('overview', '')}"
        ),
    },
    "healthcare": {
        "category": "condition",
        "build_tags": lambda data: (
            [data.get("field", "")]
            + data.get("symptoms", [])[:3]
            + [data.get("severity", "")]
        ),
        "build_content": lambda data: (
            f"{data.get('name', '')}\n"
            f"진료과: {data.get('field', '')}\n"
            f"증상: {', '.join(data.get('symptoms', []))}\n"
            f"원인: {', '.join(data.get('causes', []))}\n"
            f"치료: {', '.join(data.get('treatments', []))}\n"
            f"설명: {data.get('description', '')}"
        ),
    },
    "construction": {
        "category": "item",
        "build_tags": lambda data: (
            [data.get("type", "")]
            + data.get("usage", [])[:3]
            + [data.get("cost_level", "")]
        ),
        "build_content": lambda data: (
            f"{data.get('name', '')}\n"
            f"분류: {data.get('type', '')}\n"
            f"용도: {', '.join(data.get('usage', []))}\n"
            f"규격: {', '.join(data.get('specifications', []))}\n"
            f"설명: {data.get('description', '')}"
        ),
    },
}
OPENROUTER_BASE = "https://openrouter.ai/api/v1"

DOMAIN_LABELS = {"movie": "영화", "drama": "드라마", "healthcare": "헬스케어", "construction": "건설"}
DOMAIN_ICONS = {"movie": "🎬", "drama": "📺", "healthcare": "🏥", "construction": "🏗️"}

TOPIC_EXAMPLES = {
    "movie": ["한국 영화 TOP 30", "2024년 개봉 영화", "마블 영화 전체", "지브리 애니메이션",
              "넷플릭스 인기 영화", "아카데미 수상작", "90년대 명작 영화"],
    "drama": ["한국 드라마 역대 명작", "2024년 인기 드라마", "넷플릭스 한국 드라마",
              "tvN 인기 드라마", "SBS 드라마 명작", "로맨스 드라마 추천", "의학 드라마"],
    "healthcare": ["흔한 성인병 20가지", "영양제 종류와 효능", "운동 부상 종류",
                   "정신건강 질환", "소아 질환 20가지", "피부 질환 종류"],
    "construction": ["건축 자재 종류 20가지", "건설 공법 종류", "건설 안전 규정",
                     "인테리어 마감재 종류", "건설 중장비 종류"],
}

# Auto-rotate topics for infinite mode
AUTO_TOPICS = {
    "movie": [
        "한국 영화 역대 흥행 순위", "2024년 개봉 영화", "2023년 개봉 영화",
        "마블 MCU 영화", "아카데미 작품상 수상작", "넷플릭스 오리지널 영화",
        "지브리 스튜디오 애니메이션", "디즈니 애니메이션", "크리스토퍼 놀란 감독 영화",
        "봉준호 감독 영화", "2024년 할리우드 영화", "일본 애니메이션 명작",
        "한국 공포 영화", "90년대 할리우드 명작", "2000년대 한국 영화",
        "DC 영화", "한국 로맨스 영화", "한국 코미디 영화",
        "SF 영화 명작", "전쟁 영화 명작", "범죄 스릴러 영화",
        "2022년 개봉 영화", "2021년 개봉 영화", "2020년 개봉 영화",
    ],
    "drama": [
        "한국 드라마 역대 명작", "2024년 한국 드라마", "2023년 한국 드라마",
        "넷플릭스 한국 드라마", "tvN 인기 드라마", "SBS 드라마 명작",
        "KBS 드라마 명작", "MBC 드라마 명작", "JTBC 드라마",
        "한국 로맨스 드라마", "한국 스릴러 드라마", "한국 사극 드라마",
        "한국 의학 드라마", "한국 법정 드라마", "한국 판타지 드라마",
        "2022년 한국 드라마", "2021년 한국 드라마", "2020년 한국 드라마",
        "미국 드라마 명작", "일본 드라마 명작", "영국 드라마 명작",
    ],
    "healthcare": [
        "흔한 성인병 종류", "소아 질환", "정신건강 질환",
        "피부 질환", "소화기 질환", "호흡기 질환",
        "근골격계 질환", "비타민 종류와 효능", "미네랄 영양제",
        "운동 부상 종류", "알레르기 질환", "심혈관 질환",
        "내분비 질환", "안과 질환", "이비인후과 질환",
    ],
    "construction": [
        "건축 구조재 종류", "건축 마감재 종류", "건설 공법",
        "건설 중장비 종류", "방수 자재", "단열재 종류",
        "건설 안전 장비", "인테리어 자재", "콘크리트 종류",
        "철골 구조 종류", "지반 공사 공법", "건설 측량 장비",
    ],
}

SEARCH_QUERIES = {
    "movie": "{item} 영화 감독 출연진 줄거리 평점 개봉일",
    "drama": "{item} 드라마 연출 작가 출연진 줄거리 평점 방송사",
    "healthcare": "{item} 증상 원인 치료법 예방법",
    "construction": "{item} 건설 건축 용도 규격 특징",
}


# ── LLM Provider Detection ──────────────────────────────────────

def detect_ollama() -> dict | None:
    """Check if Ollama is running and return available models."""
    try:
        resp = httpx.get(f"{OLLAMA_BASE}/api/tags", timeout=3)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
        if models:
            return {"provider": "ollama", "models": models}
    except Exception:
        pass
    return None


def detect_openrouter() -> dict | None:
    """Check if OpenRouter API key is configured."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if api_key:
        return {
            "provider": "openrouter",
            "api_key": api_key,
            "models": ["openai/gpt-4o-mini", "openai/gpt-4.1-mini", "google/gemini-2.5-flash"],
        }
    return None


def detect_provider() -> dict:
    """Auto-detect available LLM provider. Ollama first, then OpenRouter."""
    ollama = detect_ollama()
    if ollama:
        return ollama

    openrouter = detect_openrouter()
    if openrouter:
        return openrouter

    return {"provider": "none", "models": []}


# ── LLM Call ─────────────────────────────────────────────────────

def call_llm(prompt: str, system: str, provider: str, model: str, api_key: str = "") -> str | None:
    if provider == "ollama":
        return _call_ollama(prompt, system, model)
    elif provider == "openrouter":
        return _call_openrouter(prompt, system, model, api_key)
    return None


def _call_ollama(prompt: str, system: str, model: str) -> str | None:
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    try:
        resp = httpx.post(
            f"{OLLAMA_BASE}/api/generate",
            json={
                "model": model,
                "prompt": full_prompt,
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 4096},
            },
            timeout=120.0,
        )
        resp.raise_for_status()
        return resp.json().get("response", "")
    except Exception as e:
        st.error(f"Ollama 호출 실패: {e}")
        return None


def _call_openrouter(prompt: str, system: str, model: str, api_key: str) -> str | None:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                f"{OPENROUTER_BASE}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "messages": messages, "temperature": 0.3, "max_tokens": 4096},
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        st.error(f"OpenRouter 호출 실패: {e}")
        return None


# ── Web Search ───────────────────────────────────────────────────

def web_search(query: str, max_results: int = 3) -> str:
    """Web search using built-in web scraper (httpx + bs4). No DuckDuckGo library."""
    if HAS_SCRAPER:
        try:
            scraper = WebScraper()
            text = scraper.search_and_scrape(query, max_results=max_results)
            scraper.close()
            if text:
                return text
        except Exception:
            pass
    return ""


# ── JSON Parsing ─────────────────────────────────────────────────

def parse_json(text: str) -> any:
    text = text.strip()
    # Remove think tags (qwen3)
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
    # Handle markdown code blocks
    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 2:
            code = parts[1]
            if code.startswith("json"):
                code = code[4:]
            text = code.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to extract JSON pattern
        arr_match = re.search(r'\[.*\]', text, re.DOTALL)
        obj_match = re.search(r'\{.*\}', text, re.DOTALL)
        for match in [arr_match, obj_match]:
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    continue
    return None


# ── Collector Functions ──────────────────────────────────────────

def generate_item_list(topic, count, domain, provider, model, api_key):
    """Generate item list from web search results, LLM extracts names only."""
    # Web search for real data
    search_text = web_search(f"{topic} 목록 순위", max_results=3)

    if search_text:
        prompt = (
            f"아래는 '{topic}'에 대한 웹 검색 결과입니다.\n"
            f"이 검색 결과에서 실제로 언급된 항목 이름들만 추출해서 JSON 배열로 만들어줘.\n"
            f"검색 결과에 없는 항목은 절대 추가하지 마.\n"
            f"최대 {count}개, 한국어 이름으로.\n\n"
            f"검색 결과:\n{search_text}\n\n"
            f'반드시 JSON 배열만 반환해. 예: ["항목1", "항목2"]'
        )
        system = "검색 결과에 실제로 나온 항목만 추출해. 네가 아는 지식으로 추가하지 마. JSON 배열만 반환해."
    else:
        prompt = (
            f"다음 주제에 맞는 실제로 존재하는 항목들을 JSON 배열로 나열해.\n"
            f"주제: {topic}\n최대 {count}개, 한국어 이름으로.\n\n"
            f'반드시 JSON 배열만 반환해. 예: ["항목1", "항목2"]'
        )
        system = "실제로 존재하는 항목만. JSON 배열만 반환해."

    response = call_llm(prompt, system, provider, model, api_key)
    if not response:
        return []

    result = parse_json(response)
    if isinstance(result, list):
        items = [str(item).strip() for item in result if str(item).strip()]
        # Deduplicate while preserving order
        seen = set()
        unique = []
        for item in items:
            if item not in seen:
                seen.add(item)
                unique.append(item)
        return unique[:count]

    st.error(f"JSON 파싱 실패. 응답: {response[:300]}")
    return []


def generate_detail(item, domain, provider, model, api_key):
    """Generate detail info for an item using LLM directly."""
    json_schemas = {
        "movie": (
            '{\n'
            '  "title": "한국어 제목", "original_title": "원제",\n'
            '  "release_date": "YYYY-MM-DD", "runtime": 분단위숫자,\n'
            '  "vote_average": 10점만점숫자, "genres": ["장르1", "장르2"],\n'
            '  "director": "감독 이름",\n'
            '  "cast": [{"name": "배우", "character": "역할"}],\n'
            '  "overview": "줄거리 2-3문장", "tagline": "캐치프레이즈",\n'
            '  "original_language": "ko/en/ja", "production_countries": ["국가"]\n'
            '}'
        ),
        "drama": (
            '{\n'
            '  "title": "한국어 제목", "original_title": "원제",\n'
            '  "air_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD",\n'
            '  "episodes": 총회차숫자, "runtime_per_ep": 회당분단위숫자,\n'
            '  "vote_average": 10점만점숫자, "genres": ["장르1", "장르2"],\n'
            '  "director": "연출자", "writer": "작가",\n'
            '  "cast": [{"name": "배우", "character": "역할"}],\n'
            '  "overview": "줄거리 2-3문장", "network": "방송사/플랫폼",\n'
            '  "tagline": "캐치프레이즈",\n'
            '  "original_language": "ko/en/ja", "production_countries": ["국가"]\n'
            '}'
        ),
        "healthcare": (
            '{\n'
            '  "name": "항목명", "field": "진료과",\n'
            '  "description": "설명 2-3문장",\n'
            '  "symptoms": ["증상1", "증상2"], "causes": ["원인1", "원인2"],\n'
            '  "treatments": ["치료법1"], "prevention": ["예방법1"],\n'
            '  "severity": "경미/보통/심각/만성", "age_group": "연령대",\n'
            '  "related_conditions": ["관련 질환"]\n'
            '}'
        ),
        "construction": (
            '{\n'
            '  "name": "항목명", "type": "분류",\n'
            '  "description": "설명 2-3문장",\n'
            '  "specifications": ["규격1"], "usage": ["용도1"],\n'
            '  "advantages": ["장점1"], "disadvantages": ["단점1"],\n'
            '  "related_standards": ["기준"], "cost_level": "저가/중가/고가",\n'
            '  "safety_notes": ["유의사항"]\n'
            '}'
        ),
    }

    # Web search for real data about this item
    search_query = SEARCH_QUERIES.get(domain, "{item}").format(item=item)
    search_text = web_search(search_query, max_results=2)

    prompt = f"'{item}'에 대한 정확한 정보를 JSON으로 작성해.\n"
    if search_text:
        prompt += f"\n참고 자료:\n{search_text}\n\n"
    prompt += (
        f"모르는 정보는 빈 문자열로 채워.\n\n"
        f"JSON 형식:\n{json_schemas.get(domain, '{}')}\n\n"
        f"반드시 JSON 객체만 반환해. 설명 없이."
    )

    response = call_llm(prompt, "정확한 JSON만 반환해. 설명 없이 JSON 객체만.", provider, model, api_key)
    if not response:
        return None

    result = parse_json(response)
    if isinstance(result, dict):
        return result

    st.error(f"JSON 파싱 실패 ({item}): {response[:200]}")
    return None


# ── Collection Runner ────────────────────────────────────────────

def _format_elapsed(seconds: float) -> str:
    """Format seconds into human-readable time."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}시간 {m}분 {s}초"
    elif m > 0:
        return f"{m}분 {s}초"
    return f"{s}초"


def _collect_topic(topic, count, domain, provider, model, api_key, db,
                   progress_bar, status_area, log_area,
                   live_stats=None, total_counters=None, sidebar_placeholder=None):
    """Collect a single topic. Updates live stats after each item."""
    status_area.info(f"📋 '{topic}' 항목 리스트 생성 중...")
    items = generate_item_list(topic, count, domain, provider, model, api_key)

    if not items:
        status_area.warning(f"'{topic}' 항목 리스트 생성 실패, 다음으로 넘어갑니다.")
        return {"success": [], "skipped": [], "errors": []}

    with log_area:
        st.info(f"📋 **{topic}** — {len(items)}개 항목 발견")

    status_area.info(f"📦 '{topic}' {len(items)}개 항목 수집 중...")
    results = {"success": [], "skipped": [], "errors": []}

    for i, item in enumerate(items):
        # Check if stopped
        if st.session_state.get("collect_mode") == "stopped":
            status_area.warning("수집이 중지되었습니다.")
            return results

        progress_bar.progress((i + 1) / len(items), f"[{i+1}/{len(items)}] {item}")

        schema = DOMAIN_SCHEMAS[domain]
        external_id = f"{schema['category']}_{item.replace(' ', '_')}"

        try:
            existing = db.table("domain_knowledge").select("id").eq("domain", domain).eq("external_id", external_id).execute()
            if existing.data:
                results["skipped"].append(item)
                _update_live_stats(live_stats, total_counters, results)
                _update_sidebar_counts(sidebar_placeholder, db)
                continue
        except Exception:
            pass

        data = generate_detail(item, domain, provider, model, api_key)
        if not data:
            results["errors"].append(item)
            _update_live_stats(live_stats, total_counters, results)
            continue

        try:
            title = data.get("title") or data.get("name") or item
            tags = schema["build_tags"](data)
            tags = [t for t in tags if t]
            content = schema["build_content"](data)

            db.table("domain_knowledge").insert({
                "domain": domain, "external_id": external_id,
                "category": schema["category"], "title": title,
                "content": content, "data": data, "tags": tags,
            }).execute()
            results["success"].append(item)
        except Exception as e:
            results["errors"].append(f"{item} ({e})")

        # Update live stats after each item
        _update_live_stats(live_stats, total_counters, results)
        _update_sidebar_counts(sidebar_placeholder, db)

    return results


def _update_live_stats(live_stats, total_counters, current_results):
    """Update the live stats display after each item."""
    if not live_stats or not total_counters:
        return

    ts = total_counters["success"] + len(current_results["success"])
    tsk = total_counters["skipped"] + len(current_results["skipped"])
    te = total_counters["errors"] + len(current_results["errors"])
    cycle = total_counters.get("cycle", 1)
    start_time = total_counters.get("start_time", time.time())
    elapsed = time.time() - start_time

    with live_stats.container():
        st.write(f"### ♾️ 누적 현황 (Cycle {cycle}) — ⏱️ {_format_elapsed(elapsed)}")
        tc1, tc2, tc3, tc4 = st.columns(4)
        tc1.metric("✅ 성공", ts)
        tc2.metric("⏭️ 스킵", tsk)
        tc3.metric("❌ 실패", te)
        tc4.metric("📊 전체", ts + tsk + te)
        # Speed
        if elapsed > 0 and ts > 0:
            speed = ts / (elapsed / 60)
            st.caption(f"속도: {speed:.1f}개/분 | 최근: {', '.join(current_results['success'][-3:])}")
        elif current_results["success"]:
            st.caption(f"최근 수집: {', '.join(current_results['success'][-3:])}")


def _update_sidebar_counts(sidebar_placeholder, db):
    """Update sidebar data counts in real-time."""
    if not sidebar_placeholder:
        return

    try:
        with sidebar_placeholder.container():
            total_result = db.table("domain_knowledge").select("id", count="exact").execute()
            total = total_result.count or 0
            st.metric("전체 데이터 수", f"{total}건")

            for dk, dl in DOMAIN_LABELS.items():
                result = db.table("domain_knowledge").select("id", count="exact").eq("domain", dk).execute()
                c = result.count or 0
                st.metric(f"{DOMAIN_ICONS.get(dk, '')} {dl}", f"{c}건")
    except Exception:
        pass


def _show_results(results, log_area):
    with log_area:
        c1, c2, c3 = st.columns(3)
        c1.metric("✅ 성공", len(results["success"]))
        c2.metric("⏭️ 스킵", len(results["skipped"]))
        c3.metric("❌ 실패", len(results["errors"]))
        if results["success"]:
            with st.expander(f"성공 ({len(results['success'])})"):
                st.write(", ".join(results["success"]))
        if results["errors"]:
            with st.expander(f"실패 ({len(results['errors'])})"):
                st.write(", ".join(results["errors"]))


def _run_single_topic(topic, count, domain, provider, model, api_key, db):
    """Run single topic collection."""
    progress_bar = st.progress(0, text="초기화 중...")
    status_area = st.empty()
    log_area = st.container()
    live_stats = st.empty()
    sidebar_ph = st.session_state.get("sidebar_counts")

    total_counters = {"success": 0, "skipped": 0, "errors": 0, "cycle": 1,
                      "start_time": time.time()}

    results = _collect_topic(topic, count, domain, provider, model, api_key, db,
                             progress_bar, status_area, log_area,
                             live_stats, total_counters, sidebar_ph)

    elapsed = time.time() - total_counters["start_time"]
    progress_bar.progress(1.0, f"완료! ⏱️ {_format_elapsed(elapsed)}")
    status_area.empty()
    _show_results(results, log_area)
    st.balloons()


def _generate_topic_variations(base_topic: str, domain: str, provider: str,
                                model: str, api_key: str) -> list[str]:
    """
    Generate search variations from user's topic using LLM.
    e.g. "유명한 한국 영화" →
        ["유명한 한국 영화", "한국 명작 영화", "한국 영화 추천 목록",
         "대한민국 대표 영화", "한국 영화 흥행 순위", ...]
    """
    prompt = (
        f"'{base_topic}'과 같은 의미이지만 다르게 표현한 검색 키워드를 20개 만들어줘.\n"
        f"반드시 원래 주제의 범위 안에서만 변형해. 범위를 벗어나지 마.\n"
        f"예시: '유명한 한국 영화' → '한국 명작 영화', '한국 영화 추천', '대한민국 대표 영화'\n\n"
        f'JSON 배열만 반환해. 예: ["변형1", "변형2"]'
    )
    response = call_llm(prompt, "JSON 배열만 반환해. 설명 없이.", provider, model, api_key)
    if not response:
        return [base_topic]

    result = parse_json(response)
    if isinstance(result, list):
        variations = [base_topic] + [str(v).strip() for v in result if str(v).strip()]
        # Deduplicate
        seen = set()
        unique = []
        for v in variations:
            if v.lower() not in seen:
                seen.add(v.lower())
                unique.append(v)
        return unique

    return [base_topic]


def _run_infinite(domain, count, provider, model, api_key, db, user_topic=""):
    """Run infinite collection with smart topic variation."""
    progress_bar = st.progress(0, text="무한 수집 모드 시작...")
    status_area = st.empty()
    log_area = st.container()
    live_stats = st.empty()
    sidebar_ph = st.session_state.get("sidebar_counts")

    total_counters = {"success": 0, "skipped": 0, "errors": 0, "cycle": 0,
                      "start_time": time.time()}

    # Generate topics: user topic variations first, then auto topics as fallback
    if user_topic:
        status_area.info(f"🔄 '{user_topic}' 기반으로 검색 변형 생성 중...")
        topics = _generate_topic_variations(user_topic, domain, provider, model, api_key)
        with log_area:
            st.success(f"📋 {len(topics)}개 검색 변형 생성 완료")
            with st.expander("검색 변형 목록", expanded=False):
                for i, t in enumerate(topics, 1):
                    st.write(f"{i}. {t}")
    else:
        topics = AUTO_TOPICS.get(domain, [])

    if not topics:
        st.error("주제 생성 실패")
        return

    while st.session_state.get("collect_mode") == "infinite":
        for topic_idx, topic in enumerate(topics):
            if st.session_state.get("collect_mode") != "infinite":
                break

            total_counters["cycle"] += 1
            status_area.info(
                f"♾️ **무한 수집 중** — Cycle {total_counters['cycle']} | "
                f"주제 [{topic_idx+1}/{len(topics)}]: {topic}"
            )

            results = _collect_topic(topic, count, domain, provider, model, api_key, db,
                                     progress_bar, status_area, log_area,
                                     live_stats, total_counters, sidebar_ph)

            total_counters["success"] += len(results["success"])
            total_counters["skipped"] += len(results["skipped"])
            total_counters["errors"] += len(results["errors"])

            _update_live_stats(live_stats, total_counters, {"success": [], "skipped": [], "errors": []})
            _update_sidebar_counts(sidebar_ph, db)

            if st.session_state.get("collect_mode") == "infinite":
                status_area.info(f"⏳ 다음 주제로 이동...")
                time.sleep(1)

        # One round done — generate NEW variations if user topic exists
        if st.session_state.get("collect_mode") == "infinite":
            if user_topic:
                status_area.info(f"🔄 새로운 검색 변형 생성 중...")
                new_topics = _generate_topic_variations(user_topic, domain, provider, model, api_key)
                # Filter out topics we already used
                used = set(t.lower() for t in topics)
                fresh = [t for t in new_topics if t.lower() not in used]
                if fresh:
                    topics = fresh
                    with log_area:
                        st.info(f"🔄 새로운 변형 {len(fresh)}개 생성: {', '.join(fresh[:5])}...")
                else:
                    status_area.info(f"🔄 새로운 변형이 없습니다. 60초 후 재시도...")
                    time.sleep(5)
            else:
                status_area.info(f"🔄 1회전 완료. 다시 시작...")
                time.sleep(3)

    elapsed = time.time() - total_counters["start_time"]
    progress_bar.progress(1.0, f"수집 중지됨 — ⏱️ {_format_elapsed(elapsed)}")
    status_area.success(
        f"수집 완료! 총 {total_counters['cycle']} 주제, "
        f"{total_counters['success']}개 수집, "
        f"소요 시간: {_format_elapsed(elapsed)}"
    )


# ── Supabase ─────────────────────────────────────────────────────

@st.cache_resource
def get_db():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        st.error("SUPABASE_URL, SUPABASE_KEY가 .env에 설정되어 있지 않습니다.")
        st.stop()
    return create_client(url, key)


# ── Page Config ──────────────────────────────────────────────────

st.set_page_config(page_title="Knowledge Collector", page_icon="🧠", layout="wide")
st.title("🧠 Auto Knowledge Collector")

# Init session state
if "collect_mode" not in st.session_state:
    st.session_state.collect_mode = None

db = get_db()

# ── Provider Detection & Display ─────────────────────────────────

provider_info = detect_provider()
provider = provider_info["provider"]
api_key = provider_info.get("api_key", "")
available_models = provider_info.get("models", [])

# Provider status banner
if provider == "ollama":
    st.success(f"🟢 **Ollama (로컬 LLM)** 연결됨 — 완전 무료 | 모델: {', '.join(available_models[:3])}")
elif provider == "openrouter":
    st.info("🔵 **OpenRouter API** 사용 중 — Ollama 미감지, API 키로 동작 (유료)")
else:
    st.error(
        "🔴 **LLM 없음** — 다음 중 하나를 설정하세요:\n"
        "1. Ollama 설치 후 실행 (`ollama serve`)\n"
        "2. `.env`에 `OPENROUTER_API_KEY` 설정"
    )
    st.stop()

# Web search status
if HAS_SCRAPER:
    st.caption("🔍 웹 크롤링 활성 — 검색 + 페이지 스크랩 + Wikipedia (무료)")
else:
    st.caption("⚠️ `pip install beautifulsoup4`로 웹 크롤링 활성화 가능 (무료)")


# ── Sidebar ──────────────────────────────────────────────────────

with st.sidebar:
    st.header("📊 현황")

    # Provider info
    st.divider()
    if provider == "ollama":
        st.write("🟢 **LLM**: Ollama (무료)")
    else:
        st.write("🔵 **LLM**: OpenRouter (유료)")
    if HAS_SCRAPER:
        st.write("🔍 **웹검색**: 크롤링 (무료)")
    else:
        st.write("🔍 **웹검색**: 비활성")
    st.divider()

    # Use placeholder so counts can update in real-time
    sidebar_counts = st.empty()
    st.session_state.sidebar_counts = sidebar_counts

    with sidebar_counts.container():
        try:
            all_data = db.table("domain_knowledge").select("domain", count="exact").execute()
            total_count = all_data.count or 0
        except Exception:
            total_count = 0
            st.warning("domain_knowledge 테이블이 없습니다.")

        st.metric("전체 데이터 수", f"{total_count}건")

        for dk, dl in DOMAIN_LABELS.items():
            try:
                result = db.table("domain_knowledge").select("id", count="exact").eq("domain", dk).execute()
                c = result.count or 0
            except Exception:
                c = 0
            st.metric(f"{DOMAIN_ICONS.get(dk, '')} {dl}", f"{c}건")


# ── Tabs ─────────────────────────────────────────────────────────

tab_kobis, tab_collect, tab_browse, tab_manage = st.tabs(["🎬 KOBIS 영화 수집", "📥 LLM 수집", "🔍 데이터 조회", "🗑️ 데이터 관리"])

# ── Tab 0: KOBIS ─────────────────────────────────────────────────

with tab_kobis:
    st.subheader("🎬 KOBIS 영화 수집")

    kobis_key = os.environ.get("KOBIS_API_KEY")
    if kobis_key:
        st.success(f"🟢 KOBIS API 연결됨 — 영화진흥위원회 공식 데이터 (무료, LLM 불필요)")
    else:
        st.error("🔴 KOBIS_API_KEY가 .env에 없습니다. https://kobis.or.kr/kobisopenapi 에서 발급하세요.")

    st.info("KOBIS(영화진흥위원회) + 네이버 크롤링으로 **실제 영화 데이터**를 수집합니다.\n\n"
            "- 감독, 배우, 장르 → KOBIS 공식 API\n"
            "- 줄거리, 평점 → 네이버 크롤링\n"
            "- LLM 비용 **0원**, 가짜 영화 **0개**")

    kobis_mode = st.selectbox("수집 모드", [
        "monthly", "weekly", "search", "infinite"
    ], format_func=lambda x: {
        "monthly": "📊 월별 박스오피스 TOP 10 (최근 N개월)",
        "weekly": "📅 주간 박스오피스 (최근 N주)",
        "search": "🔍 연도별 전체 영화",
        "infinite": "♾️ 무한 수집 (월별 박스오피스 + 전 연도)",
    }[x], key="kobis_mode")

    kcol1, kcol2 = st.columns(2)
    with kcol1:
        if kobis_mode == "monthly":
            kobis_months = st.slider("수집 기간 (개월)", 1, 120, 12, 1, key="kobis_months")
        elif kobis_mode == "weekly":
            kobis_weeks = st.slider("수집 기간 (주)", 4, 208, 52, 4, key="kobis_weeks")
        elif kobis_mode == "search":
            current_year = datetime.now().year
            kobis_year = st.selectbox("연도", range(current_year, 1989, -1), key="kobis_year")
    with kcol2:
        st.caption("**예상 수집량**")
        if kobis_mode == "monthly":
            st.write(f"~{min(kobis_months * 10, kobis_months * 8)}편 (월 TOP 10, 중복 제거)")
        elif kobis_mode == "weekly":
            st.write(f"~{kobis_weeks * 5}편 (주 TOP 10, 중복 제거)")
        elif kobis_mode == "search":
            st.write("해당 연도 개봉 전체 영화")
        elif kobis_mode == "infinite":
            st.write("1990~현재 전체 영화 (수천편)")

    st.divider()

    kcol_start, kcol_stop = st.columns(2)
    with kcol_start:
        kobis_start = st.button("🚀 KOBIS 수집 시작", type="primary",
                                disabled=not kobis_key, use_container_width=True)
    with kcol_stop:
        if st.session_state.get("kobis_running"):
            if st.button("⏹️ 수집 중지", key="kobis_stop", use_container_width=True):
                st.session_state.kobis_running = False
                st.rerun()

    if kobis_start and kobis_key:
        st.session_state.kobis_running = True

        try:
            from kobis_collector import KobisCollector
        except ImportError:
            from scripts.kobis_collector import KobisCollector

        progress_bar = st.progress(0, text="KOBIS 수집 시작...")
        status_area = st.empty()
        live_stats = st.empty()
        log_area = st.container()
        sidebar_ph = st.session_state.get("sidebar_counts")

        collector = KobisCollector()
        start_time = time.time()

        # Monkey-patch stats display into collector
        original_process = collector._process_movie

        processed_count = {"n": 0, "success": 0}

        def _patched_process(movie_cd, movie_name):
            if not st.session_state.get("kobis_running"):
                return
            original_process(movie_cd, movie_name)
            processed_count["n"] += 1
            processed_count["success"] = collector.stats["success"]
            elapsed = time.time() - start_time

            # Update progress display
            status_area.info(f"🎬 수집 중: {movie_name}")
            with live_stats.container():
                st.write(f"### 🎬 KOBIS 수집 현황 — ⏱️ {_format_elapsed(elapsed)}")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("✅ 성공", collector.stats["success"])
                c2.metric("⏭️ 스킵", collector.stats["skipped"])
                c3.metric("❌ 실패", collector.stats["errors"])
                c4.metric("📊 전체", collector.stats["total"])
                if elapsed > 0 and collector.stats["success"] > 0:
                    speed = collector.stats["success"] / (elapsed / 60)
                    st.caption(f"속도: {speed:.1f}편/분")

            _update_sidebar_counts(sidebar_ph, db)

        collector._process_movie = _patched_process

        try:
            if kobis_mode == "monthly":
                collector.collect_monthly_boxoffice(months=kobis_months)
            elif kobis_mode == "weekly":
                collector.collect_weekly_boxoffice(weeks=kobis_weeks)
            elif kobis_mode == "search":
                collector.collect_by_year(year=kobis_year)
            elif kobis_mode == "infinite":
                collector.collect_infinite()
        except Exception as e:
            st.error(f"수집 중 오류: {e}")

        elapsed = time.time() - start_time
        progress_bar.progress(1.0, f"완료! ⏱️ {_format_elapsed(elapsed)}")
        status_area.success(
            f"KOBIS 수집 완료! 성공: {collector.stats['success']}편, "
            f"스킵: {collector.stats['skipped']}편, "
            f"소요 시간: {_format_elapsed(elapsed)}"
        )
        collector.close()
        st.session_state.kobis_running = False
        st.balloons()


# ── Tab 1: Collect ───────────────────────────────────────────────

with tab_collect:
    st.subheader("새 데이터 수집")

    col1, col2 = st.columns(2)
    with col1:
        domain = st.selectbox("도메인", options=list(DOMAIN_LABELS.keys()),
                              format_func=lambda x: f"{DOMAIN_ICONS.get(x, '')} {DOMAIN_LABELS[x]}")
    with col2:
        count = st.slider("주제당 수집 항목 수", 5, 50, 20, 5)

    model = st.selectbox("LLM 모델", options=available_models, index=0)

    # Topic examples
    st.write("**주제 예시:**")
    examples = TOPIC_EXAMPLES.get(domain, [])
    example_cols = st.columns(min(len(examples), 4))
    if "selected_topic" not in st.session_state:
        st.session_state.selected_topic = ""
    for i, ex in enumerate(examples):
        with example_cols[i % 4]:
            if st.button(ex, key=f"ex_{domain}_{i}", use_container_width=True):
                st.session_state.selected_topic = ex

    topic = st.text_input("수집 주제", value=st.session_state.selected_topic,
                          placeholder=f"예: {examples[0] if examples else ''}")

    st.divider()

    # ── Two modes: Single topic vs Infinite ──
    mode_col1, mode_col2 = st.columns(2)

    with mode_col1:
        if st.button("🚀 1회 수집", type="primary", disabled=not topic, use_container_width=True):
            st.session_state.collect_mode = "single"

    with mode_col2:
        if st.button("♾️ 무한 수집 시작", type="secondary", use_container_width=True):
            st.session_state.collect_mode = "infinite"

    # Stop button for infinite mode
    if st.session_state.get("collect_mode") == "infinite":
        if st.button("⏹️ 수집 중지", use_container_width=True):
            st.session_state.collect_mode = "stopped"
            st.rerun()

    # ── Single topic collection ──
    if st.session_state.get("collect_mode") == "single" and topic:
        _run_single_topic(topic, count, domain, provider, model, api_key, db)
        st.session_state.collect_mode = None

    # ── Infinite collection ──
    if st.session_state.get("collect_mode") == "infinite":
        _run_infinite(domain, count, provider, model, api_key, db, user_topic=topic)


# ── Tab 2: Browse ────────────────────────────────────────────────

with tab_browse:
    # Header with refresh and Supabase status
    hcol1, hcol2, hcol3 = st.columns([4, 1, 2])
    with hcol1:
        st.subheader("데이터 조회")
    with hcol2:
        refresh = st.button("🔄 새로고침", key="refresh_browse", use_container_width=True)
    with hcol3:
        # Supabase connection check
        try:
            db.table("domain_knowledge").select("id").limit(1).execute()
            st.success("🟢 Supabase 연결됨", icon="✅")
        except Exception:
            st.error("🔴 Supabase 연결 실패", icon="❌")

    cf1, cf2, cf3 = st.columns([2, 2, 3])
    with cf1:
        browse_domain = st.selectbox("도메인", ["all"] + list(DOMAIN_LABELS.keys()),
                                     format_func=lambda x: "전체" if x == "all" else f"{DOMAIN_ICONS.get(x, '')} {DOMAIN_LABELS[x]}",
                                     key="bd")
    with cf2:
        try:
            cq = db.table("domain_knowledge").select("category")
            if browse_domain != "all":
                cq = cq.eq("domain", browse_domain)
            cat_result = cq.execute()
            cats = sorted(set(r["category"] for r in cat_result.data)) if cat_result.data else []
        except Exception:
            cats = []
        browse_cat = st.selectbox("카테고리", ["all"] + cats,
                                  format_func=lambda x: "전체" if x == "all" else x, key="bc")
    with cf3:
        sq = st.text_input("🔍 검색", placeholder="검색어...", key="sq")

    try:
        q = db.table("domain_knowledge").select("*")
        if browse_domain != "all":
            q = q.eq("domain", browse_domain)
        if browse_cat != "all":
            q = q.eq("category", browse_cat)
        if sq:
            q = q.ilike("content", f"%{sq}%")
        items = q.order("created_at", desc=True).limit(50).execute().data or []
    except Exception as e:
        items = []
        st.warning(f"조회 실패: {e}")

    # Count with DB status indicator
    try:
        count_q = db.table("domain_knowledge").select("id", count="exact")
        if browse_domain != "all":
            count_q = count_q.eq("domain", browse_domain)
        if browse_cat != "all":
            count_q = count_q.eq("category", browse_cat)
        if sq:
            count_q = count_q.ilike("content", f"%{sq}%")
        total_in_db = count_q.execute().count or 0
        st.caption(f"📊 Supabase 내 전체: **{total_in_db}건** | 현재 표시: {len(items)}건 (최대 50)")
    except Exception:
        st.caption(f"{len(items)}건 (최대 50)")

    if not items:
        st.info("데이터가 없습니다. '데이터 수집' 탭에서 시작하세요!")
    for item in items:
        di = DOMAIN_ICONS.get(item["domain"], "📦")
        data = item.get("data", {})
        created = item.get("created_at", "")[:19].replace("T", " ") if item.get("created_at") else ""

        with st.expander(
            f"{di} **{item['title']}** — "
            f"{DOMAIN_LABELS.get(item['domain'], item['domain'])} | "
            f"🟢 DB 저장됨 {f'| 🕐 {created}' if created else ''}"
        ):
            if item["domain"] == "movie":
                c1, c2 = st.columns([1, 2])
                with c1:
                    st.write(f"**감독:** {data.get('director', '-')}")
                    try:
                        r = float(data.get('vote_average', 0) or 0)
                    except (ValueError, TypeError):
                        r = 0
                    st.write(f"**평점:** {'⭐' * round(r / 2)} {r}/10")
                    st.write(f"**장르:** {', '.join(data.get('genres', []))}")
                    st.write(f"**개봉:** {data.get('release_date', '-')}")
                with c2:
                    if data.get("overview"):
                        st.write(f"**줄거리:** {data['overview']}")
                    if data.get("cast"):
                        st.write(f"**출연:** {', '.join(c.get('name', '') for c in data['cast'][:5])}")
            elif item["domain"] == "drama":
                c1, c2 = st.columns([1, 2])
                with c1:
                    st.write(f"**연출:** {data.get('director', '-')}")
                    st.write(f"**작가:** {data.get('writer', '-')}")
                    try:
                        r = float(data.get('vote_average', 0) or 0)
                    except (ValueError, TypeError):
                        r = 0
                    st.write(f"**평점:** {'⭐' * round(r / 2)} {r}/10")
                    st.write(f"**장르:** {', '.join(data.get('genres', []))}")
                    st.write(f"**방송사:** {data.get('network', '-')}")
                    ep = data.get('episodes')
                    st.write(f"**회차:** {f'{ep}부작' if ep else '-'}")
                    st.write(f"**방영:** {data.get('air_date', '-')}")
                with c2:
                    if data.get("overview"):
                        st.write(f"**줄거리:** {data['overview']}")
                    if data.get("cast"):
                        st.write(f"**출연:** {', '.join(c.get('name', '') for c in data['cast'][:5])}")
            elif item["domain"] == "healthcare":
                c1, c2 = st.columns([1, 2])
                with c1:
                    st.write(f"**진료과:** {data.get('field', '-')}")
                    st.write(f"**심각도:** {data.get('severity', '-')}")
                with c2:
                    if data.get("description"):
                        st.write(f"**설명:** {data['description']}")
                    if data.get("symptoms"):
                        st.write(f"**증상:** {', '.join(data['symptoms'])}")
                    if data.get("treatments"):
                        st.write(f"**치료:** {', '.join(data['treatments'])}")
            elif item["domain"] == "construction":
                c1, c2 = st.columns([1, 2])
                with c1:
                    st.write(f"**분류:** {data.get('type', '-')}")
                    st.write(f"**비용:** {data.get('cost_level', '-')}")
                with c2:
                    if data.get("description"):
                        st.write(f"**설명:** {data['description']}")
                    if data.get("usage"):
                        st.write(f"**용도:** {', '.join(data['usage'])}")
            else:
                st.json(data)

            if item.get("tags"):
                tag_html = " ".join(
                    f'<span style="background:#e2e8f0;padding:2px 8px;border-radius:12px;font-size:12px;">{t}</span>'
                    for t in item["tags"] if t
                )
                st.markdown(tag_html, unsafe_allow_html=True)


# ── Tab 3: Manage ────────────────────────────────────────────────

with tab_manage:
    st.subheader("데이터 관리")
    st.warning("삭제된 데이터는 복구할 수 없습니다.")

    cm1, cm2 = st.columns(2)
    with cm1:
        st.write("#### 도메인별 초기화")
        rd = st.selectbox("도메인", list(DOMAIN_LABELS.keys()),
                          format_func=lambda x: f"{DOMAIN_ICONS.get(x, '')} {DOMAIN_LABELS[x]}", key="rd")
        try:
            rc = db.table("domain_knowledge").select("id", count="exact").eq("domain", rd).execute().count or 0
        except Exception:
            rc = 0
        st.caption(f"현재 {rc}건")
        if st.button(f"🗑️ {DOMAIN_LABELS[rd]} 전체 삭제"):
            if rc == 0:
                st.info("삭제할 데이터 없음")
            else:
                db.table("domain_knowledge").delete().eq("domain", rd).execute()
                st.success(f"{rc}건 삭제 완료!")
                st.rerun()

    with cm2:
        st.write("#### 개별 삭제")
        ds = st.text_input("제목 검색", placeholder="검색...", key="ds")
        if ds:
            try:
                sr = db.table("domain_knowledge").select("id,domain,title").ilike("title", f"%{ds}%").limit(10).execute().data or []
            except Exception:
                sr = []
            for item in sr:
                c1, c2 = st.columns([3, 1])
                c1.write(f"{DOMAIN_ICONS.get(item['domain'], '')} {item['title']}")
                if c2.button("삭제", key=f"d_{item['id']}"):
                    db.table("domain_knowledge").delete().eq("id", item["id"]).execute()
                    st.success(f"삭제 완료!")
                    st.rerun()
