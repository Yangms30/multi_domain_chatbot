"""
Auto Knowledge Collector - Uses LLM + Web Search to automatically collect domain knowledge.

Pipeline:
    1. LLM generates a list of items to collect
    2. Web search gathers raw information for each item
    3. LLM structures the raw data into DB schema
    4. Store in Supabase domain_knowledge table

Usage:
    python -m scripts.auto_collector --domain movie --topic "한국 영화 TOP 50"
    python -m scripts.auto_collector --domain movie --topic "2024년 개봉 영화"
    python -m scripts.auto_collector --domain healthcare --topic "흔한 성인병 30가지"
    python -m scripts.auto_collector --domain construction --topic "건축 자재 종류 20가지"

Uses OpenRouter API (already configured in .env) for LLM calls.
LLM cost is ONE-TIME during collection. Chatbot responses use DB only.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time

import httpx
from dotenv import load_dotenv
from supabase import create_client

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# ── Domain schema definitions ────────────────────────────────────
# Tells the LLM what structure to produce for each domain

DOMAIN_SCHEMAS = {
    "movie": {
        "description": "영화 정보",
        "list_prompt": "다음 주제에 맞는 영화 제목들을 JSON 배열로 나열해줘. 제목만, 한국어로. 최대 {count}개.\n주제: {topic}",
        "detail_prompt": (
            "다음 영화에 대한 정보를 정확하게 JSON으로 작성해줘. 모르는 정보는 빈 문자열로.\n"
            "영화: {item}\n\n"
            "JSON 형식:\n"
            '{{\n'
            '  "title": "한국어 제목",\n'
            '  "original_title": "원제",\n'
            '  "release_date": "YYYY-MM-DD",\n'
            '  "runtime": 분단위숫자,\n'
            '  "vote_average": 10점만점숫자,\n'
            '  "genres": ["장르1", "장르2"],\n'
            '  "director": "감독 이름",\n'
            '  "cast": [\n'
            '    {{"name": "배우이름", "character": "역할"}}\n'
            '  ],\n'
            '  "overview": "줄거리 5문장 이상",\n'
            '  "tagline": "대표 대사나 캐치프레이즈",\n'
            '  "original_language": "ko/en/ja 등",\n'
            '  "production_countries": ["한국"]\n'
            '}}'
        ),
        "category": "movie",
        "build_tags": lambda data: (
            data.get("genres", [])
            + [data.get("director", "")]
            + [c["name"] for c in data.get("cast", [])[:5]]
            + [data.get("original_language", "")]
        ),
        "build_content": lambda data: (
            f"{data.get('title', '')} ({data.get('release_date', '')[:4] if data.get('release_date') else '미정'})\n"
            f"감독: {data.get('director', '')}\n"
            f"출연: {', '.join(c['name'] for c in data.get('cast', [])[:5])}\n"
            f"장르: {', '.join(data.get('genres', []))}\n"
            f"평점: {data.get('vote_average', 0)}/10\n"
            f"줄거리: {data.get('overview', '')}"
        ),
    },
    "healthcare": {
        "description": "의료/건강 정보",
        "list_prompt": "다음 주제에 맞는 항목들을 JSON 배열로 나열해줘. 항목명만, 한국어로. 최대 {count}개.\n주제: {topic}",
        "detail_prompt": (
            "다음 의료/건강 항목에 대한 정보를 정확하게 JSON으로 작성해줘. 모르는 정보는 빈 문자열로.\n"
            "항목: {item}\n\n"
            "JSON 형식:\n"
            '{{\n'
            '  "name": "질병/건강 항목명",\n'
            '  "field": "진료과 (예: 내과, 정형외과)",\n'
            '  "description": "설명 2-3문장",\n'
            '  "symptoms": ["증상1", "증상2", "증상3"],\n'
            '  "causes": ["원인1", "원인2"],\n'
            '  "treatments": ["치료법1", "치료법2"],\n'
            '  "prevention": ["예방법1", "예방법2"],\n'
            '  "severity": "경미/보통/심각/만성",\n'
            '  "age_group": "주요 발생 연령대",\n'
            '  "related_conditions": ["관련 질환1"]\n'
            '}}'
        ),
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
            f"예방: {', '.join(data.get('prevention', []))}\n"
            f"설명: {data.get('description', '')}"
        ),
    },
    "construction": {
        "description": "건설/건축 정보",
        "list_prompt": "다음 주제에 맞는 항목들을 JSON 배열로 나열해줘. 항목명만, 한국어로. 최대 {count}개.\n주제: {topic}",
        "detail_prompt": (
            "다음 건설/건축 항목에 대한 정보를 정확하게 JSON으로 작성해줘. 모르는 정보는 빈 문자열로.\n"
            "항목: {item}\n\n"
            "JSON 형식:\n"
            '{{\n'
            '  "name": "항목명",\n'
            '  "type": "분류 (자재/공법/장비/규정 등)",\n'
            '  "description": "설명 2-3문장",\n'
            '  "specifications": ["규격1", "규격2"],\n'
            '  "usage": ["용도1", "용도2"],\n'
            '  "advantages": ["장점1", "장점2"],\n'
            '  "disadvantages": ["단점1", "단점2"],\n'
            '  "related_standards": ["관련 기준/법규"],\n'
            '  "cost_level": "저가/중가/고가",\n'
            '  "safety_notes": ["안전 유의사항"]\n'
            '}}'
        ),
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
            f"장점: {', '.join(data.get('advantages', []))}\n"
            f"단점: {', '.join(data.get('disadvantages', []))}\n"
            f"설명: {data.get('description', '')}"
        ),
    },
}


class AutoCollector:
    def __init__(self, domain: str, model: str = "qwen/qwen-3.5-72b-instruct"):
        self.domain = domain
        self.model = model
        self.schema = DOMAIN_SCHEMAS[domain]
        self.stats = {"total": 0, "success": 0, "skipped": 0, "errors": 0}

        # OpenRouter
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY is required in .env")
        self.llm_client = httpx.AsyncClient(
            base_url=OPENROUTER_BASE_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )

        # Supabase
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_KEY required in .env")
        self.db = create_client(url, key)

    async def run(self, topic: str, count: int = 20):
        logger.info("=== Step 1: LLM으로 항목 리스트 생성 ===")
        items = await self._generate_item_list(topic, count)
        if not items:
            logger.error("항목 리스트 생성 실패")
            return
        logger.info("생성된 항목: %d개", len(items))
        for i, item in enumerate(items, 1):
            logger.info("  %d. %s", i, item)

        logger.info("\n=== Step 2: 각 항목 상세 정보 수집 ===")
        for i, item in enumerate(items, 1):
            self.stats["total"] += 1
            logger.info("[%d/%d] %s 처리 중...", i, len(items), item)

            # Check if already exists
            external_id = f"{self.schema['category']}_{item.replace(' ', '_')}"
            existing = (
                self.db.table("domain_knowledge")
                .select("id")
                .eq("domain", self.domain)
                .eq("external_id", external_id)
                .execute()
            )
            if existing.data:
                logger.info("  → 이미 존재, 스킵")
                self.stats["skipped"] += 1
                continue

            # Get detail from LLM
            data = await self._generate_detail(item)
            if not data:
                logger.error("  → 상세 정보 생성 실패")
                self.stats["errors"] += 1
                continue

            # Build and store
            try:
                title = data.get("title") or data.get("name") or item
                tags = self.schema["build_tags"](data)
                tags = [t for t in tags if t]  # remove empty
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

            # Rate limit: avoid hitting API too fast
            await asyncio.sleep(1)

    async def _generate_item_list(self, topic: str, count: int) -> list[str]:
        prompt = self.schema["list_prompt"].format(topic=topic, count=count)
        response = await self._call_llm(
            prompt,
            system="JSON 배열만 반환해. 설명 없이 배열만. 예: [\"항목1\", \"항목2\"]"
        )
        if not response:
            return []

        try:
            # Extract JSON array from response
            response = response.strip()
            # Handle markdown code blocks
            if "```" in response:
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]
                response = response.strip()

            items = json.loads(response)
            if isinstance(items, list):
                return [str(item) for item in items]
        except json.JSONDecodeError:
            logger.error("JSON 파싱 실패: %s", response[:200])

        return []

    async def _generate_detail(self, item: str) -> dict | None:
        prompt = self.schema["detail_prompt"].format(item=item)
        response = await self._call_llm(
            prompt,
            system="정확한 JSON만 반환해. 설명이나 마크다운 없이 JSON 객체만. 정확한 사실 정보만 포함해."
        )
        if not response:
            return None

        try:
            response = response.strip()
            if "```" in response:
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]
                response = response.strip()

            data = json.loads(response)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            logger.error("JSON 파싱 실패: %s", response[:200])

        return None

    async def _call_llm(self, prompt: str, system: str = "") -> str | None:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        try:
            resp = await self.llm_client.post("/chat/completions", json={
                "model": self.model,
                "messages": messages,
                "temperature": 0.3,
                "max_tokens": 4096,
            })
            resp.raise_for_status()
            result = resp.json()
            return result["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error("LLM 호출 실패: %s", e)
            return None

    async def close(self):
        await self.llm_client.aclose()


async def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Auto Knowledge Collector")
    parser.add_argument("--domain", required=True, choices=list(DOMAIN_SCHEMAS.keys()),
                        help="Domain to collect data for")
    parser.add_argument("--topic", required=True,
                        help='Topic to collect (e.g., "한국 영화 TOP 50")')
    parser.add_argument("--count", type=int, default=20,
                        help="Number of items to collect (default: 20)")
    parser.add_argument("--model", default="openai/gpt-4o-mini",
                        help="LLM model to use (default: gpt-4o-mini)")
    args = parser.parse_args()

    collector = AutoCollector(domain=args.domain, model=args.model)

    logger.info("=== Auto Knowledge Collector ===")
    logger.info("Domain: %s | Topic: %s | Count: %d | Model: %s",
                args.domain, args.topic, args.count, args.model)

    start_time = time.time()
    await collector.run(topic=args.topic, count=args.count)
    elapsed = time.time() - start_time

    await collector.close()

    s = collector.stats
    logger.info("\n=== 완료 (%.1f초) ===", elapsed)
    logger.info("전체: %d | 성공: %d | 스킵: %d | 실패: %d",
                s["total"], s["success"], s["skipped"], s["errors"])


if __name__ == "__main__":
    asyncio.run(main())
