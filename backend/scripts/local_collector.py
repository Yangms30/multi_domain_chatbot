"""
Local Knowledge Collector - 100% Free, runs 24/7

Uses:
- DuckDuckGo: Free web search (no API key)
- Ollama: Local LLM (no API cost)
- Supabase: Data storage

Setup:
    1. Install Ollama: https://ollama.com/download
    2. Pull a model: ollama pull qwen3:4b
    3. pip install duckduckgo-search
    4. Run: python -m scripts.local_collector --domain movie --topic "한국 영화 TOP 50"

Continuous mode (24h):
    python -m scripts.local_collector --domain movie --continuous --interval 3600
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime

import httpx
from dotenv import load_dotenv
from supabase import create_client

try:
    from duckduckgo_search import DDGS
except ImportError:
    print("duckduckgo-search 패키지가 필요합니다: pip install duckduckgo-search")
    sys.exit(1)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

OLLAMA_BASE = "http://localhost:11434"

# ── Domain schemas ───────────────────────────────────────────────

DOMAIN_SCHEMAS = {
    "movie": {
        "search_query": "{item} 영화 감독 출연진 줄거리 평점 개봉일",
        "json_schema": (
            '{{\n'
            '  "title": "한국어 제목",\n'
            '  "original_title": "원제",\n'
            '  "release_date": "YYYY-MM-DD",\n'
            '  "runtime": 분단위숫자,\n'
            '  "vote_average": 10점만점숫자,\n'
            '  "genres": ["장르1", "장르2"],\n'
            '  "director": "감독 이름",\n'
            '  "cast": [{{"name": "배우", "character": "역할"}}],\n'
            '  "overview": "줄거리 2-3문장",\n'
            '  "tagline": "캐치프레이즈",\n'
            '  "original_language": "ko/en/ja",\n'
            '  "production_countries": ["국가"]\n'
            '}}'
        ),
        "category": "movie",
        "list_query": "{topic} 목록",
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
    "healthcare": {
        "search_query": "{item} 증상 원인 치료법 예방법",
        "json_schema": (
            '{{\n'
            '  "name": "질병/건강 항목명",\n'
            '  "field": "진료과",\n'
            '  "description": "설명 2-3문장",\n'
            '  "symptoms": ["증상1", "증상2"],\n'
            '  "causes": ["원인1", "원인2"],\n'
            '  "treatments": ["치료법1", "치료법2"],\n'
            '  "prevention": ["예방법1", "예방법2"],\n'
            '  "severity": "경미/보통/심각/만성",\n'
            '  "age_group": "주요 발생 연령대",\n'
            '  "related_conditions": ["관련 질환"]\n'
            '}}'
        ),
        "category": "condition",
        "list_query": "{topic} 목록",
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
        "search_query": "{item} 건설 건축 용도 규격 특징",
        "json_schema": (
            '{{\n'
            '  "name": "항목명",\n'
            '  "type": "분류 (자재/공법/장비/규정)",\n'
            '  "description": "설명 2-3문장",\n'
            '  "specifications": ["규격1", "규격2"],\n'
            '  "usage": ["용도1", "용도2"],\n'
            '  "advantages": ["장점1", "장점2"],\n'
            '  "disadvantages": ["단점1", "단점2"],\n'
            '  "related_standards": ["관련 기준"],\n'
            '  "cost_level": "저가/중가/고가",\n'
            '  "safety_notes": ["안전 유의사항"]\n'
            '}}'
        ),
        "category": "item",
        "list_query": "{topic} 목록",
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

# ── Continuous mode topic rotation ────────────────────────────────

AUTO_TOPICS = {
    "movie": [
        "한국 영화 역대 흥행 TOP 50",
        "2024년 개봉 한국 영화",
        "2023년 개봉 한국 영화",
        "마블 MCU 영화 전체",
        "아카데미 작품상 수상작",
        "넷플릭스 오리지널 영화",
        "지브리 스튜디오 애니메이션",
        "디즈니 애니메이션 영화",
        "크리스토퍼 놀란 감독 영화",
        "봉준호 감독 영화",
        "2024년 개봉 할리우드 영화",
        "일본 애니메이션 명작",
        "한국 공포 영화",
        "90년대 할리우드 명작",
        "2000년대 한국 영화 명작",
    ],
    "healthcare": [
        "흔한 성인병 종류",
        "흔한 소아 질환",
        "정신건강 질환 종류",
        "피부 질환 종류",
        "소화기 질환 종류",
        "호흡기 질환 종류",
        "근골격계 질환 종류",
        "비타민 영양제 종류와 효능",
        "미네랄 영양제 종류와 효능",
        "운동 부상 종류",
    ],
    "construction": [
        "건축 구조재 종류",
        "건축 마감재 종류",
        "건설 공법 종류",
        "건설 중장비 종류",
        "방수 자재 종류",
        "단열재 종류",
        "건설 안전 장비",
        "인테리어 자재 종류",
    ],
}


class LocalCollector:
    def __init__(self, domain: str, model: str = "qwen3:4b"):
        self.domain = domain
        self.model = model
        self.schema = DOMAIN_SCHEMAS[domain]
        self.stats = {"total": 0, "success": 0, "skipped": 0, "errors": 0}
        self.ddgs = DDGS()

        # Check Ollama
        try:
            resp = httpx.get(f"{OLLAMA_BASE}/api/tags", timeout=5)
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
            if not any(model.split(":")[0] in m for m in models):
                logger.warning("모델 '%s'이 없습니다. 설치: ollama pull %s", model, model)
                logger.info("설치된 모델: %s", models)
        except Exception:
            raise RuntimeError(
                "Ollama가 실행 중이지 않습니다.\n"
                "1. Ollama 설치: https://ollama.com/download\n"
                "2. 모델 다운로드: ollama pull qwen3:4b\n"
                "3. Ollama 실행 후 다시 시도하세요."
            )

        # Supabase
        load_dotenv()
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL, SUPABASE_KEY가 .env에 필요합니다.")
        self.db = create_client(url, key)

    def run_topic(self, topic: str, count: int = 20):
        """Collect data for a single topic."""
        logger.info("=" * 50)
        logger.info("주제: %s | 항목 수: %d", topic, count)
        logger.info("=" * 50)

        # Step 1: Get item list from web search + LLM
        logger.info("Step 1: 항목 리스트 생성...")
        items = self._generate_item_list(topic, count)
        if not items:
            logger.error("항목 리스트 생성 실패")
            return
        logger.info("생성된 항목 %d개: %s", len(items), ", ".join(items[:10]))

        # Step 2: Collect details for each item
        logger.info("Step 2: 상세 정보 수집...")
        for i, item in enumerate(items, 1):
            self.stats["total"] += 1
            external_id = f"{self.schema['category']}_{item.replace(' ', '_')}"

            # Skip if exists
            try:
                existing = (
                    self.db.table("domain_knowledge")
                    .select("id")
                    .eq("domain", self.domain)
                    .eq("external_id", external_id)
                    .execute()
                )
                if existing.data:
                    logger.info("[%d/%d] %s → 스킵 (이미 존재)", i, len(items), item)
                    self.stats["skipped"] += 1
                    continue
            except Exception:
                pass

            logger.info("[%d/%d] %s 수집 중...", i, len(items), item)

            # Web search
            search_results = self._web_search(item)
            if not search_results:
                logger.warning("  → 검색 결과 없음, LLM 지식으로 대체")
                search_results = "검색 결과 없음"

            # LLM structuring
            data = self._structure_with_llm(item, search_results)
            if not data:
                logger.error("  → JSON 생성 실패")
                self.stats["errors"] += 1
                continue

            # Store
            try:
                title = data.get("title") or data.get("name") or item
                tags = self.schema["build_tags"](data)
                tags = [t for t in tags if t]
                content = self.schema["build_content"](data)

                self.db.table("domain_knowledge").insert({
                    "domain": self.domain,
                    "external_id": external_id,
                    "category": self.schema["category"],
                    "title": title,
                    "content": content,
                    "data": data,
                    "tags": tags,
                }).execute()

                self.stats["success"] += 1
                logger.info("  → 저장 완료: %s", title)
            except Exception as e:
                logger.error("  → 저장 실패: %s", e)
                self.stats["errors"] += 1

            time.sleep(2)  # DuckDuckGo rate limit

    def run_continuous(self, interval: int = 3600):
        """Run continuously, rotating through auto topics."""
        topics = AUTO_TOPICS.get(self.domain, [])
        if not topics:
            logger.error("'%s' 도메인에 자동 주제가 없습니다.", self.domain)
            return

        cycle = 0
        while True:
            cycle += 1
            topic = topics[(cycle - 1) % len(topics)]
            logger.info("\n🔄 Cycle %d | %s | %s",
                        cycle, datetime.now().strftime("%Y-%m-%d %H:%M"), topic)

            try:
                self.run_topic(topic, count=20)
            except Exception as e:
                logger.error("주제 '%s' 수집 중 오류: %s", topic, e)

            self._print_stats()

            if cycle < len(topics):
                # Still have topics to process, short break
                logger.info("다음 주제까지 30초 대기...")
                time.sleep(30)
            else:
                # All topics done for this round
                logger.info("모든 주제 1회전 완료. %d초 후 다시 시작...", interval)
                time.sleep(interval)

    # ── Web Search ────────────────────────────────────────────────

    def _web_search(self, item: str) -> str:
        query = self.schema["search_query"].format(item=item)
        try:
            results = self.ddgs.text(query, max_results=5)
            if not results:
                return ""

            # Combine search results into text
            texts = []
            for r in results:
                title = r.get("title", "")
                body = r.get("body", "")
                texts.append(f"[{title}] {body}")

            return "\n".join(texts)
        except Exception as e:
            logger.warning("웹검색 실패 (%s): %s", item, e)
            return ""

    # ── LLM Structuring ──────────────────────────────────────────

    def _generate_item_list(self, topic: str, count: int) -> list[str]:
        """Generate item list from WEB SEARCH, not LLM memory."""
        # Search multiple queries to get comprehensive real data
        search_queries = [
            topic,
            f"{topic} 순위",
            f"{topic} 리스트 목록",
        ]

        all_search_text = []
        for q in search_queries:
            try:
                results = self.ddgs.text(q, max_results=5)
                if results:
                    text = "\n".join(
                        f"[{r.get('title', '')}] {r.get('body', '')}" for r in results
                    )
                    all_search_text.append(text)
            except Exception:
                pass
            time.sleep(1)

        combined_search = "\n\n".join(all_search_text)

        # LLM role: EXTRACT names from search results only
        if combined_search:
            prompt = (
                f"아래는 '{topic}'에 대한 웹 검색 결과입니다.\n"
                f"이 검색 결과에서 실제로 언급된 항목 이름들만 추출해서 JSON 배열로 만들어줘.\n"
                f"검색 결과에 없는 항목은 절대 추가하지 마.\n"
                f"최대 {count}개, 한국어 이름으로.\n\n"
                f"검색 결과:\n{combined_search}\n\n"
                f'반드시 JSON 배열만 반환해. 예: ["항목1", "항목2"]'
            )
        else:
            logger.warning("웹 검색 결과 없음, LLM 지식으로 시도")
            prompt = (
                f"다음 주제에 맞는 항목들을 JSON 배열로 나열해.\n"
                f"주제: {topic}\n최대 {count}개, 한국어 이름으로.\n\n"
                f'반드시 JSON 배열만 반환해. 예: ["항목1", "항목2"]'
            )

        response = self._call_ollama(prompt)
        if not response:
            return []

        items = self._parse_json_array(response)
        # Deduplicate
        seen = set()
        unique = []
        for item in items:
            if item not in seen:
                seen.add(item)
                unique.append(item)
        return unique[:count]

    def _structure_with_llm(self, item: str, search_results: str) -> dict | None:
        prompt = (
            f"다음 검색 결과를 바탕으로 '{item}'에 대한 정보를 JSON으로 정리해.\n"
            f"검색 결과에 없는 정보는 빈 문자열로 채워.\n\n"
            f"검색 결과:\n{search_results}\n\n"
            f"JSON 형식:\n{self.schema['json_schema']}\n\n"
            f"반드시 JSON 객체만 반환해. 설명 없이."
        )

        response = self._call_ollama(prompt)
        if not response:
            return None

        return self._parse_json_object(response)

    def _call_ollama(self, prompt: str) -> str | None:
        try:
            resp = httpx.post(
                f"{OLLAMA_BASE}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.3,
                        "num_predict": 4096,
                    },
                },
                timeout=120.0,
            )
            resp.raise_for_status()
            return resp.json().get("response", "")
        except httpx.ConnectError:
            logger.error("Ollama 연결 실패. ollama serve가 실행 중인지 확인하세요.")
            return None
        except Exception as e:
            logger.error("Ollama 호출 실패: %s", e)
            return None

    # ── JSON Parsing ──────────────────────────────────────────────

    def _parse_json_array(self, text: str) -> list[str]:
        text = self._extract_json(text)
        try:
            result = json.loads(text)
            if isinstance(result, list):
                return [str(item) for item in result]
        except json.JSONDecodeError:
            # Try to find array pattern in text
            import re
            match = re.search(r'\[.*\]', text, re.DOTALL)
            if match:
                try:
                    result = json.loads(match.group())
                    if isinstance(result, list):
                        return [str(item) for item in result]
                except json.JSONDecodeError:
                    pass
            logger.error("JSON 배열 파싱 실패: %s", text[:200])
        return []

    def _parse_json_object(self, text: str) -> dict | None:
        text = self._extract_json(text)
        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            # Try to find object pattern in text
            import re
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                try:
                    result = json.loads(match.group())
                    if isinstance(result, dict):
                        return result
                except json.JSONDecodeError:
                    pass
            logger.error("JSON 객체 파싱 실패: %s", text[:200])
        return None

    def _extract_json(self, text: str) -> str:
        text = text.strip()
        # Remove think tags (qwen3 sometimes outputs these)
        import re
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
        # Handle markdown code blocks
        if "```" in text:
            parts = text.split("```")
            if len(parts) >= 2:
                code = parts[1]
                if code.startswith("json"):
                    code = code[4:]
                text = code.strip()
        return text

    def _print_stats(self):
        s = self.stats
        logger.info("--- 누적 통계: 전체 %d | 성공 %d | 스킵 %d | 실패 %d ---",
                     s["total"], s["success"], s["skipped"], s["errors"])


def main():
    parser = argparse.ArgumentParser(description="Local Knowledge Collector (Free)")
    parser.add_argument("--domain", required=True, choices=list(DOMAIN_SCHEMAS.keys()))
    parser.add_argument("--topic", help='수집 주제 (e.g., "한국 영화 TOP 50")')
    parser.add_argument("--count", type=int, default=20, help="항목 수 (default: 20)")
    parser.add_argument("--model", default="qwen3:4b", help="Ollama 모델 (default: qwen3:4b)")
    parser.add_argument("--continuous", action="store_true", help="24시간 연속 수집 모드")
    parser.add_argument("--interval", type=int, default=3600, help="연속 모드 주기 (초, default: 3600)")
    args = parser.parse_args()

    collector = LocalCollector(domain=args.domain, model=args.model)

    if args.continuous:
        logger.info("🔄 연속 수집 모드 시작 (Ctrl+C로 중지)")
        logger.info("도메인: %s | 모델: %s | 주기: %d초", args.domain, args.model, args.interval)
        try:
            collector.run_continuous(interval=args.interval)
        except KeyboardInterrupt:
            logger.info("\n수집 중지됨")
            collector._print_stats()
    else:
        if not args.topic:
            parser.error("--topic이 필요합니다 (또는 --continuous 사용)")

        start = time.time()
        collector.run_topic(args.topic, args.count)
        elapsed = time.time() - start

        collector._print_stats()
        logger.info("소요 시간: %.1f초", elapsed)


if __name__ == "__main__":
    main()
