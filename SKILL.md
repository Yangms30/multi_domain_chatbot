# Chatbot Skill

## 목적
이 파일을 읽으면 친구 같고 비서 같은 느낌의 챗봇을 기존 프로젝트에 맞춰 만들 수 있다.
음성 대화, 장기 기억, OpenRouter LLM 연동이 핵심 기능이다.

---

## 반드시 먼저 할 것 (프로젝트 파악)

SKILL.md를 읽은 후 코드를 작성하기 **전에** 반드시 아래 순서로 기존 프로젝트를 파악한다.

```
1. 프로젝트 루트의 파일/폴더 구조를 확인한다
2. 프론트엔드 프레임워크를 파악한다 (React / Vue / Next.js / 순수 HTML 등)
3. 백엔드 프레임워크를 파악한다 (FastAPI / Express / Django / Next.js API 등)
4. 기존 패키지 파일을 확인한다 (package.json / requirements.txt / pyproject.toml)
5. 기존 환경변수 파일을 확인한다 (.env / .env.local 등)
6. 파악한 내용을 사용자에게 먼저 요약해서 보여주고 확인받는다
```

파악한 스택에 맞게 아래 구현 가이드를 적용한다.
기존 파일은 절대 덮어쓰지 않고, 기존 코드 스타일과 구조를 따른다.

---

## 챗봇 페르소나

모든 LLM 호출 시 아래 system prompt를 항상 첫 번째 메시지로 포함한다.

```
You are a friendly AI assistant who feels like a close friend and a helpful personal assistant at the same time.

Personality traits:
- Warm, casual, and conversational — like texting a good friend
- Proactive and helpful — like a smart personal assistant
- Always remember the user's personal details (name, preferences, past topics) and reference them naturally
- Use the user's name when you know it
- Korean and English both supported — match the language the user uses

Memory rules:
- When the user shares personal info (name, age, job, hobby, location, etc.), remember it and save it
- Reference past conversations naturally: "아, 저번에 말씀하셨던 그거요?"
- Never ask for information the user already told you

Tone:
- Friendly but not overly casual
- Encouraging and positive
- Short responses for casual chat, detailed when help is needed
```

---

## LLM 설정

- 기본 모델: `qwen/qwen3-5b` (OpenRouter)
- API endpoint: `https://openrouter.ai/api/v1/chat/completions`
- 환경변수 키: `OPENROUTER_API_KEY`
- 기존 프로젝트에 `.env` 파일이 있으면 거기에 추가한다. 없으면 새로 생성한다.

```env
OPENROUTER_API_KEY=your_key_here
DEFAULT_MODEL=qwen/qwen3-5b
```

OpenRouter 호출 예시:
```python
headers = {
    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
    "Content-Type": "application/json",
}
body = {
    "model": "qwen/qwen3-5b",
    "messages": [
        {"role": "system", "content": SYSTEM_PROMPT},
        ...대화기록...,
        {"role": "user", "content": user_message}
    ]
}
```

---

## 핵심 기능 3가지

### 1. 기억 시스템

대화 내역과 사용자 개인정보를 영구 저장한다.

**저장소 선택 기준:**
- 기존 프로젝트에 DB가 있으면 (PostgreSQL, MySQL 등) → 그 DB에 테이블 추가
- DB가 없으면 → SQLite 파일로 로컬 저장
- Node.js 프로젝트면 → better-sqlite3 또는 lowdb 사용

**저장할 데이터:**
```
conversations 테이블:
  - id, role (user/assistant), content, timestamp

user_info 테이블:
  - key (예: "name", "age", "hobby"), value, updated_at
```

**LLM 호출 시 기억 주입 방식:**
```
system prompt
  + "\n\nKnown user information:\n- name: 홍길동\n- hobby: 독서"  ← user_info에서 조합
  + 최근 대화 20개  ← conversations에서 조회
```

---

### 2. OpenRouter LLM 연동

**백엔드가 Python이면:**
```python
import httpx
import os

async def chat(user_message: str, history: list, user_info: dict) -> str:
    memory_str = "\n".join([f"- {k}: {v}" for k, v in user_info.items()])
    system = SYSTEM_PROMPT
    if memory_str:
        system += f"\n\nKnown user information:\n{memory_str}"

    messages = [{"role": "system", "content": system}]
    messages += history  # 최근 20개
    messages.append({"role": "user", "content": user_message})

    async with httpx.AsyncClient() as client:
        res = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}"},
            json={"model": os.getenv("DEFAULT_MODEL", "qwen/qwen3-5b"), "messages": messages},
            timeout=30.0
        )
    return res.json()["choices"][0]["message"]["content"]
```

**백엔드가 Node.js / Next.js이면:**
```typescript
import OpenAI from "openai"; // openai SDK가 OpenRouter와 호환됨

const client = new OpenAI({
  baseURL: "https://openrouter.ai/api/v1",
  apiKey: process.env.OPENROUTER_API_KEY,
});

async function chat(userMessage: string, history: any[], userInfo: Record<string, string>) {
  const memoryStr = Object.entries(userInfo).map(([k, v]) => `- ${k}: ${v}`).join("\n");
  const system = memoryStr
    ? `${SYSTEM_PROMPT}\n\nKnown user information:\n${memoryStr}`
    : SYSTEM_PROMPT;

  const response = await client.chat.completions.create({
    model: process.env.DEFAULT_MODEL || "qwen/qwen3-5b",
    messages: [{ role: "system", content: system }, ...history, { role: "user", content: userMessage }],
  });
  return response.choices[0].message.content;
}
```

---

### 3. 음성 기능 (STT / TTS)

**STT (음성 → 텍스트):**
- Python: `faster-whisper` (small 모델, CPU 가능)
- Node.js: OpenAI Whisper API 또는 `whisper.cpp` 바인딩

**TTS (텍스트 → 음성):**
- Python: `piper-tts` (로컬, 무료) 또는 네이버 CLOVA Voice (한국어 품질 우수)
- Node.js: Web Speech API (브라우저 내장, 별도 설치 불필요)

**음성 흐름:**
```
[사용자 마이크] → WAV/WebM blob → POST /api/voice
  → STT로 텍스트 변환
  → LLM으로 응답 생성
  → TTS로 음성 변환
  → 음성 파일 반환 + 재생
```

**프론트엔드 음성 녹음 (프레임워크 무관 공통 로직):**
```javascript
let mediaRecorder, audioChunks = [];

async function startRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  mediaRecorder = new MediaRecorder(stream);
  audioChunks = [];
  mediaRecorder.ondataavailable = (e) => audioChunks.push(e.data);
  mediaRecorder.onstop = async () => {
    const blob = new Blob(audioChunks, { type: "audio/webm" });
    const formData = new FormData();
    formData.append("audio", blob, "voice.webm");
    const res = await fetch("/api/voice", { method: "POST", body: formData });
    // 응답 처리 (텍스트 or 음성)
  };
  mediaRecorder.start();
}

function stopRecording() {
  mediaRecorder.stop();
}
```

---

## API 엔드포인트 설계

기존 라우팅 규칙에 맞게 경로를 조정한다.
(Next.js면 `/app/api/`, FastAPI면 `@app.post()`, Express면 `router.post()`)

| 엔드포인트 | 메서드 | 기능 |
|-----------|--------|------|
| `/api/chat` | POST | 텍스트 채팅, `{ message }` 입력 → `{ reply }` 반환 |
| `/api/voice` | POST | 음성 입력, FormData(audio) → WAV 반환 + 헤더에 transcript/reply |
| `/api/memory` | GET | 대화 기록 조회 |
| `/api/memory/clear` | DELETE | 대화 기록 초기화 |

---

## UI 컴포넌트 추가 방식

기존 프론트엔드 프레임워크에 맞게 컴포넌트를 추가한다.

**React / Next.js이면:**
- `components/ChatWidget.tsx` 파일로 분리
- 기존 레이아웃 컴포넌트 안에 import해서 사용

**Vue이면:**
- `components/ChatWidget.vue` 파일로 분리

**순수 HTML이면:**
- 기존 HTML 파일에 채팅 UI 섹션 추가

**UI에 반드시 포함할 요소:**
```
- 대화 메시지 목록 (user / assistant 구분)
- 텍스트 입력창 + 전송 버튼
- 음성 녹음 버튼 (누르는 동안 녹음 or 토글)
- 로딩 인디케이터 (LLM 응답 대기 중)
```

---

## 패키지 추가 방법

기존 패키지 파일에 추가한다. 새 파일을 만들지 않는다.

**Python (requirements.txt 또는 pyproject.toml에 추가):**
```
httpx
faster-whisper
piper-tts
python-multipart
```

**Node.js (package.json에 추가):**
```
openai
```

---

## 주의사항

1. 기존 파일 구조와 네이밍 컨벤션을 반드시 따른다
2. 기존 인증/미들웨어가 있으면 새 API 엔드포인트에도 동일하게 적용한다
3. 환경변수는 기존 `.env` 파일에 추가한다 (새로 만들지 않음)
4. 기존 DB가 있으면 새 DB를 만들지 않고 기존 DB에 테이블을 추가한다
5. Piper 한국어 모델은 별도 다운로드 필요: https://huggingface.co/rhasspy/piper-voices
6. 한국어 TTS 품질이 중요하면 Piper 대신 네이버 CLOVA Voice API 무료 플랜 사용 권장
