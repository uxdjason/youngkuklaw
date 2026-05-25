"""
LLM Abstraction Layer (migration/src/migration/ai/llm.py)
기능 요약:
- 인터페이스: async def call(prompt: str, *, system: str = "", model_hint: str = "primary", cache_keys: list[str] = None, max_tokens: int = 4096) -> LLMResult
- 우선순위: primary(claude-sonnet-4-6) -> secondary(claude-haiku-4-5) -> fallback(gemini-2.5-pro)
- Retry: exponential backoff, max 3회. 429/5xx/timeout만 재시도.
- Prompt caching: system + glossary는 항상 cache_control에 표시.
- 사용량/비용 자동 로깅 -> ai_calls 테이블.
- 모든 응답은 LLMResult(text, model_used, usage, cost_usd, raw)로 normalize.
- 환경변수 PRIMARY_MODEL 등으로 오버라이드 가능.
"""
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

@dataclass
class LLMResult:
    text: str
    model_used: str
    usage: Dict[str, int]
    cost_usd: float
    raw: Any

class LLMClient:
    async def call(
        self,
        prompt: str,
        *,
        system: str = "",
        model_hint: str = "primary",
        cache_keys: Optional[List[str]] = None,
        max_tokens: int = 4096,
        tools: Optional[List[Dict]] = None
    ) -> LLMResult:
        # TODO: 실제 구현
        pass
