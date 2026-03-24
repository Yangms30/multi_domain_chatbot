"""
Rule-based response engine for multi-domain chatbot.
Handles simple queries without LLM calls to save cost and reduce latency.
"""

import re

from services.knowledge_query import KnowledgeQuery


class RuleEngine:
    """Classifies user intent and returns rule-based responses when possible."""

    def __init__(self):
        self._faq_database = self._build_faq_database()
        self._knowledge = KnowledgeQuery()

    def try_respond(self, message: str, domain: str) -> tuple[str, str] | None:
        """
        Try to generate a rule-based response.
        Returns (response, function_name) tuple if handled, None if LLM should handle it.
        """
        # Try DB knowledge query first (works for any domain with data)
        kb_result = self._knowledge.try_respond(message, domain)
        if kb_result:
            return kb_result

        if domain != "healthcare":
            return None

        message_lower = message.strip().lower()

        # 1. BMI calculation
        bmi_response = self._try_bmi(message_lower, message)
        if bmi_response:
            return (bmi_response, "BMI 계산기")

        # 2. Calorie calculation
        calorie_response = self._try_calorie(message_lower, message)
        if calorie_response:
            return (calorie_response, "칼로리 조회")

        # 3. FAQ matching
        faq_response = self._try_faq(message_lower)
        if faq_response:
            return (faq_response, "건강 FAQ")

        # 4. Simple greetings
        greeting_response = self._try_greeting(message_lower)
        if greeting_response:
            return (greeting_response, "인사말")

        return None

    # ── BMI Calculator ──────────────────────────────────────────────

    def _try_bmi(self, msg_lower: str, msg_original: str) -> str | None:
        if "bmi" not in msg_lower and "체질량" not in msg_lower:
            return None

        # Try to extract height/weight using cm/kg markers first
        height_cm = self._extract_with_marker(msg_lower, [r"(\d+\.?\d*)\s*cm", r"키\s*(\d+\.?\d*)"])
        weight_kg = self._extract_with_marker(msg_lower, [r"(\d+\.?\d*)\s*kg", r"몸무게\s*(\d+\.?\d*)", r"체중\s*(\d+\.?\d*)"])

        # Fallback: if markers not found, use positional heuristic with exactly 2 numbers
        if height_cm is None or weight_kg is None:
            numbers = re.findall(r"(\d+\.?\d*)", msg_original)
            if len(numbers) == 2:
                v1, v2 = float(numbers[0]), float(numbers[1])
                height_cm = max(v1, v2)
                weight_kg = min(v1, v2)

        if height_cm is None or weight_kg is None:
            return (
                "BMI를 계산하려면 키와 몸무게가 필요합니다!\n\n"
                "예시: **\"키 175cm 몸무게 70kg BMI 알려줘\"**\n\n"
                "키(cm)와 몸무게(kg)를 함께 알려주세요."
            )

        # Sanity check
        if height_cm < 50 or height_cm > 250 or weight_kg < 20 or weight_kg > 300:
            return None  # Fall through to LLM

        height_m = height_cm / 100
        bmi = weight_kg / (height_m ** 2)
        bmi_rounded = round(bmi, 1)

        category, emoji, advice = self._bmi_category(bmi)

        return (
            f"## {emoji} BMI 계산 결과\n\n"
            f"| 항목 | 값 |\n"
            f"|------|----|\n"
            f"| 키 | {height_cm:.0f} cm |\n"
            f"| 몸무게 | {weight_kg:.1f} kg |\n"
            f"| **BMI** | **{bmi_rounded}** |\n"
            f"| 판정 | {category} |\n\n"
            f"{advice}\n\n"
            f"---\n"
            f"*BMI = 체중(kg) ÷ 키(m)²*\n"
            f"*더 자세한 건강 상담이 필요하면 편하게 질문해주세요!*"
        )

    def _bmi_category(self, bmi: float) -> tuple[str, str, str]:
        if bmi < 18.5:
            return (
                "저체중",
                "⚠️",
                "체중이 다소 부족합니다. 균형 잡힌 식단으로 건강한 체중 증가를 목표로 해보세요. "
                "단백질과 건강한 지방 섭취를 늘리는 것이 좋습니다."
            )
        elif bmi < 23:
            return (
                "정상",
                "✅",
                "건강한 체중 범위입니다! 현재의 생활 습관을 잘 유지하세요. "
                "규칙적인 운동과 균형 잡힌 식사를 계속하시면 됩니다."
            )
        elif bmi < 25:
            return (
                "과체중",
                "⚠️",
                "약간 과체중 범위입니다. 식단 조절과 주 3-4회 30분 이상의 유산소 운동을 추천합니다. "
                "작은 변화부터 시작해보세요!"
            )
        else:
            return (
                "비만",
                "🔴",
                "비만 범위에 해당합니다. 생활습관 개선이 필요합니다. "
                "전문의 상담과 함께 식단 관리, 규칙적인 운동을 시작하시는 것을 권장합니다."
            )

    # ── Calorie Calculator ──────────────────────────────────────────

    def _try_calorie(self, msg_lower: str, msg_original: str) -> str | None:
        calorie_keywords = ["칼로리", "열량", "kcal"]
        food_calories = {
            "밥": ("밥 1공기 (210g)", 310),
            "라면": ("라면 1봉지", 500),
            "치킨": ("치킨 1조각 (허벅지)", 250),
            "피자": ("피자 1조각", 270),
            "김밥": ("김밥 1줄", 330),
            "떡볶이": ("떡볶이 1인분", 380),
            "삼겹살": ("삼겹살 1인분 (200g)", 580),
            "비빔밥": ("비빔밥 1인분", 550),
            "된장찌개": ("된장찌개 1인분", 150),
            "김치찌개": ("김치찌개 1인분", 200),
            "불고기": ("불고기 1인분 (200g)", 400),
            "샐러드": ("샐러드 1인분", 150),
            "아메리카노": ("아메리카노 1잔", 5),
            "카페라떼": ("카페라떼 1잔", 180),
            "콜라": ("콜라 1캔 (355ml)", 140),
            "맥주": ("맥주 1캔 (500ml)", 230),
            "소주": ("소주 1잔 (50ml)", 65),
            "사과": ("사과 1개", 95),
            "바나나": ("바나나 1개", 105),
            "계란": ("계란 1개", 80),
            "우유": ("우유 1잔 (200ml)", 130),
            "고구마": ("고구마 1개 (중)", 130),
            "닭가슴살": ("닭가슴살 100g", 110),
            "햄버거": ("햄버거 1개", 500),
            "떡": ("떡 1인분 (100g)", 230),
        }

        if not any(kw in msg_lower for kw in calorie_keywords):
            return None

        # Sort by key length descending to match longer names first
        # This prevents "밥" from matching inside "김밥" or "비빔밥"
        sorted_foods = sorted(food_calories.items(), key=lambda x: len(x[0]), reverse=True)
        matched_text = msg_lower
        found = []
        for food, (desc, cal) in sorted_foods:
            if food in matched_text:
                found.append((desc, cal))
                # Remove matched food to prevent substring overlap
                matched_text = matched_text.replace(food, "", 1)

        if not found:
            return None  # Fall through to LLM for unknown foods

        total = sum(cal for _, cal in found)
        rows = "\n".join(f"| {desc} | {cal} kcal |" for desc, cal in found)

        return (
            f"## 🍽️ 칼로리 정보\n\n"
            f"| 음식 | 칼로리 |\n"
            f"|------|--------|\n"
            f"{rows}\n"
            f"| **합계** | **{total} kcal** |\n\n"
            f"*일반적인 성인 하루 권장 칼로리: 남성 2,500kcal / 여성 2,000kcal*\n\n"
            f"*정확한 칼로리는 조리법에 따라 달라질 수 있습니다. "
            f"더 자세한 영양 상담이 필요하면 질문해주세요!*"
        )

    # ── FAQ Database ────────────────────────────────────────────────

    def _build_faq_database(self) -> list[dict]:
        return [
            {
                "keywords": ["간헐적 단식", "간헐적단식", "16:8", "16 8 단식"],
                "answer": (
                    "## 간헐적 단식이란?\n\n"
                    "간헐적 단식은 **일정 시간 동안 음식을 먹지 않고, 정해진 시간에만 식사하는 방법**입니다.\n\n"
                    "### 주요 방법\n"
                    "- **16:8 방식**: 16시간 공복 + 8시간 내 식사 (가장 인기)\n"
                    "- **5:2 방식**: 주 5일 정상 식사 + 2일 저칼로리 (500-600kcal)\n"
                    "- **24시간 단식**: 주 1-2회 24시간 공복\n\n"
                    "### 기대 효과\n"
                    "- 체중 감량 및 체지방 감소\n"
                    "- 인슐린 민감성 개선\n"
                    "- 세포 자가포식(autophagy) 촉진\n\n"
                    "### 주의사항\n"
                    "- 당뇨병, 저혈압 환자는 반드시 의사와 상담\n"
                    "- 임산부/수유부는 피하기\n"
                    "- 처음엔 12:12부터 시작하는 것을 권장\n\n"
                    "*더 자세한 내용이 궁금하면 질문해주세요!*"
                ),
            },
            {
                "keywords": ["물 얼마나", "하루 물", "물 섭취량", "물 많이"],
                "answer": (
                    "## 💧 하루 권장 물 섭취량\n\n"
                    "일반적으로 **하루 1.5~2리터 (8잔)** 를 권장합니다.\n\n"
                    "### 더 많이 마셔야 할 때\n"
                    "- 운동할 때 (운동 전후 500ml 추가)\n"
                    "- 더운 날씨\n"
                    "- 카페인/알코올 섭취 시\n"
                    "- 체중이 많이 나갈수록 (체중 kg × 30ml)\n\n"
                    "### 팁\n"
                    "- 한 번에 많이 마시기보다 **조금씩 자주** 마시기\n"
                    "- 기상 직후 물 한 잔으로 시작\n"
                    "- 소변 색이 연한 노란색이면 적당한 수분 상태\n\n"
                    "*체중에 맞는 정확한 양이 궁금하면 체중을 알려주세요!*"
                ),
            },
            {
                "keywords": ["스트레칭", "스트레칭 방법", "스트레칭 루틴"],
                "answer": (
                    "## 🧘 기본 스트레칭 루틴 (10분)\n\n"
                    "### 상체\n"
                    "1. **목 스트레칭** - 좌우로 천천히 기울이기 (15초씩)\n"
                    "2. **어깨 돌리기** - 앞뒤로 10회씩\n"
                    "3. **팔 교차 스트레칭** - 팔을 반대쪽으로 당기기 (15초씩)\n\n"
                    "### 하체\n"
                    "4. **허벅지 앞면** - 한 발로 서서 발목 잡기 (15초씩)\n"
                    "5. **허벅지 뒷면** - 다리 펴고 앞으로 숙이기 (20초)\n"
                    "6. **종아리** - 벽에 손 대고 뒤꿈치 누르기 (15초씩)\n\n"
                    "### 주의사항\n"
                    "- 통증이 느껴지면 즉시 멈추기\n"
                    "- 반동 주지 않고 천천히\n"
                    "- 호흡을 멈추지 않기\n\n"
                    "*부위별 상세 스트레칭이 필요하면 알려주세요!*"
                ),
            },
            {
                "keywords": ["수면 시간", "잠 시간", "몇 시간 자", "수면 권장", "잠을 못"],
                "answer": (
                    "## 😴 권장 수면 시간\n\n"
                    "| 연령대 | 권장 수면 시간 |\n"
                    "|--------|---------------|\n"
                    "| 성인 (18-64세) | 7-9시간 |\n"
                    "| 고령자 (65세+) | 7-8시간 |\n"
                    "| 청소년 (14-17세) | 8-10시간 |\n\n"
                    "### 좋은 수면을 위한 팁\n"
                    "- 매일 같은 시간에 자고 일어나기\n"
                    "- 잠자리 1시간 전 스마트폰/PC 끄기\n"
                    "- 카페인은 오후 2시 이후 피하기\n"
                    "- 침실 온도 18-20°C 유지\n"
                    "- 저녁 과식 피하기\n\n"
                    "*수면에 대해 더 궁금한 점이 있으면 편하게 질문해주세요!*"
                ),
            },
            {
                "keywords": ["단백질 섭취", "단백질 얼마나", "단백질 권장", "프로틴"],
                "answer": (
                    "## 💪 하루 단백질 권장 섭취량\n\n"
                    "| 활동 수준 | 체중 1kg당 |\n"
                    "|-----------|----------|\n"
                    "| 일반 성인 | 0.8-1.0g |\n"
                    "| 운동하는 사람 | 1.2-1.6g |\n"
                    "| 근력 운동 (벌크업) | 1.6-2.2g |\n"
                    "| 다이어트 중 | 1.2-1.5g |\n\n"
                    "### 예시 (체중 70kg 기준)\n"
                    "- 일반: 56-70g/일\n"
                    "- 운동: 84-112g/일\n\n"
                    "### 단백질이 풍부한 음식\n"
                    "- 닭가슴살 100g → 31g\n"
                    "- 계란 1개 → 7g\n"
                    "- 두부 1모 → 24g\n"
                    "- 그릭요거트 1컵 → 15g\n\n"
                    "*체중과 운동 목표를 알려주시면 맞춤 추천해드릴게요!*"
                ),
            },
            {
                "keywords": ["기초대사량", "기초 대사량", "bmr"],
                "answer": (
                    "## 🔥 기초대사량(BMR)이란?\n\n"
                    "아무것도 하지 않고 가만히 있어도 생명 유지를 위해 소모되는 **최소 에너지량**입니다.\n\n"
                    "### 평균 기초대사량\n"
                    "- 성인 남성: 약 **1,500-1,800 kcal/일**\n"
                    "- 성인 여성: 약 **1,200-1,500 kcal/일**\n\n"
                    "### BMR에 영향을 주는 요소\n"
                    "- 근육량 (많을수록 높음)\n"
                    "- 나이 (나이 들수록 감소)\n"
                    "- 성별, 체중, 키\n\n"
                    "### 기초대사량 높이는 법\n"
                    "- 근력 운동으로 근육량 증가\n"
                    "- 단백질 충분히 섭취\n"
                    "- 극단적인 다이어트 피하기\n"
                    "- 충분한 수면\n\n"
                    "*키, 몸무게, 나이, 성별을 알려주시면 BMR을 계산해드릴게요!*"
                ),
            },
        ]

    def _try_faq(self, msg_lower: str) -> str | None:
        best_match = None
        best_score = 0

        for faq in self._faq_database:
            score = sum(1 for kw in faq["keywords"] if kw in msg_lower)
            if score > best_score:
                best_score = score
                best_match = faq

        if best_score > 0:
            return best_match["answer"]

        return None

    # ── Greetings ───────────────────────────────────────────────────

    def _try_greeting(self, msg_lower: str) -> str | None:
        greetings = {
            "안녕": "안녕하세요! 😊 건강과 관련된 궁금한 점이 있으시면 편하게 질문해주세요!",
            "하이": "안녕하세요! 건강 코치입니다. 무엇을 도와드릴까요?",
            "hello": "안녕하세요! 건강에 대해 궁금한 점이 있으시면 말씀해주세요!",
            "hi": "안녕하세요! 건강 상담이 필요하시면 편하게 질문해주세요!",
        }

        # Only match if message is short (likely a pure greeting)
        if len(msg_lower) > 15:
            return None

        for trigger, response in greetings.items():
            if trigger in msg_lower:
                return response

        return None

    # ── Helpers ──────────────────────────────────────────────────────

    def _extract_with_marker(self, text: str, patterns: list[str]) -> float | None:
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return float(match.group(1))
        return None
