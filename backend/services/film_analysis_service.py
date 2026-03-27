"""
Film Analysis Service - builds analysis-specific LLM prompts from movie context.
Uses DB movie data to reduce hallucination and provide structured analysis.
"""

import json


# Focus category detection
FOCUS_KEYWORDS = {
    "촬영": "cinematography",
    "연출": "cinematography",
    "카메라": "cinematography",
    "영상미": "cinematography",
    "스토리": "narrative",
    "서사": "narrative",
    "구조": "narrative",
    "플롯": "narrative",
    "각본": "narrative",
    "테마": "theme",
    "상징": "theme",
    "메시지": "theme",
    "의미": "theme",
    "철학": "theme",
}

FULL_ANALYSIS_PROMPT = """당신은 영화 전문 분석가입니다. 아래 영화 정보를 바탕으로 전문적인 분석을 제공하세요.

{movie_info}

다음 항목에 대해 분석해주세요:

## 촬영/연출 분석
감독의 연출 스타일, 촬영 기법, 시각적 특징을 분석해주세요.

## 스토리/서사 구조
서사 구조, 주요 플롯 포인트, 전개 방식을 분석해주세요.

## 테마/상징
핵심 테마, 상징적 요소, 사회적/철학적 메시지를 해석해주세요.

## 총평
영화사적 의미와 이 영화를 추천할 대상을 정리해주세요.

규칙:
- 한국어로 답변
- 각 섹션 2-3문장
- 스포일러가 포함될 경우 **[스포일러 주의]** 표시
- 주관적 의견과 객관적 사실을 구분"""

FOCUSED_PROMPTS = {
    "cinematography": """당신은 영화 촬영/연출 전문 분석가입니다. 아래 영화의 촬영 기법과 연출을 깊이 분석해주세요.

{movie_info}

## 촬영/연출 심층 분석

다음을 포함해서 분석해주세요:
- 촬영 기법 (카메라 워크, 앵글, 조명)
- 감독의 연출 스타일과 특징
- 시각적 스타일과 색감
- 특수효과나 기술적 성취
- 다른 작품과의 비교

규칙: 한국어, 5-7문장, 스포일러 시 **[스포일러 주의]** 표시""",

    "narrative": """당신은 영화 서사/스토리 전문 분석가입니다. 아래 영화의 스토리 구조를 깊이 분석해주세요.

{movie_info}

## 스토리/서사 심층 분석

다음을 포함해서 분석해주세요:
- 서사 구조 (3막 구조, 비선형 등)
- 주요 플롯 포인트와 전환점
- 캐릭터 아크 (주인공의 변화)
- 서브플롯과 메인 플롯의 관계
- 결말의 의미

규칙: 한국어, 5-7문장, **[스포일러 주의]** 표시 필수""",

    "theme": """당신은 영화 테마/상징 전문 분석가입니다. 아래 영화의 테마와 상징을 깊이 해석해주세요.

{movie_info}

## 테마/상징 심층 분석

다음을 포함해서 분석해주세요:
- 핵심 테마와 메시지
- 상징적 요소 (반복되는 이미지, 오브제)
- 사회적/정치적 맥락
- 철학적 질문
- 감독이 전달하려는 세계관

규칙: 한국어, 5-7문장, 스포일러 시 **[스포일러 주의]** 표시""",
}


class FilmAnalysisService:
    """Builds analysis-specific LLM messages from movie context."""

    def build_messages(self, movie_context: dict, user_message: str) -> list[dict]:
        """Build LLM messages with movie data injected."""
        movie_info = self._format_movie_info(movie_context)
        focus = self.detect_focus(user_message)

        if focus and focus in FOCUSED_PROMPTS:
            system_content = FOCUSED_PROMPTS[focus].format(movie_info=movie_info)
        else:
            system_content = FULL_ANALYSIS_PROMPT.format(movie_info=movie_info)

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_message},
        ]

        return messages

    def detect_focus(self, message: str) -> str | None:
        """Detect if user wants a specific analysis category."""
        msg_lower = message.lower()
        for keyword, category in FOCUS_KEYWORDS.items():
            if keyword in msg_lower:
                return category
        return None

    def _format_movie_info(self, ctx: dict) -> str:
        """Format movie context dict into readable text for the prompt."""
        if not ctx.get("from_db", False):
            return f"[영화 정보]\n제목: {ctx.get('title', '알 수 없음')}\n(DB에 상세 정보가 없습니다. 알고 있는 지식을 바탕으로 분석해주세요.)"

        parts = [
            "[영화 정보]",
            f"제목: {ctx.get('title', '')}",
        ]

        if ctx.get("director"):
            parts.append(f"감독: {ctx['director']}")
        if ctx.get("genres"):
            genres = ctx["genres"]
            if isinstance(genres, list):
                genres = ", ".join(genres)
            parts.append(f"장르: {genres}")
        if ctx.get("release_date"):
            parts.append(f"개봉: {ctx['release_date']}")
        if ctx.get("vote_average"):
            parts.append(f"평점: {ctx['vote_average']}/10")
        if ctx.get("cast"):
            cast = ctx["cast"]
            if isinstance(cast, list):
                cast = ", ".join(cast[:5])
            parts.append(f"출연: {cast}")
        if ctx.get("overview"):
            parts.append(f"줄거리: {ctx['overview']}")

        return "\n".join(parts)
