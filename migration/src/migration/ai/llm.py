"""
llm.py — LLM 추상 레이어 (Phase 4)

기능:
- Claude Sonnet 4.6 (primary) → Claude Haiku 4.5 (secondary) → Gemini 2.5 Pro (fallback)
- 429/5xx/timeout 시 exponential backoff 재시도 (1s, 4s, 9s, max 3회)
- Claude prompt caching (system + glossary를 cache_control로 표시)
- Claude web search 도구 지원 (research 단계)
- 모든 호출 결과 ai_calls 테이블 + ai_log.jsonl 기록
- 환경변수 PRIMARY_MODEL 등으로 오버라이드 가능
"""

import asyncio
import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import anthropic
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
# 모델 설정
# ─────────────────────────────────────────────

PRIMARY_MODEL   = os.getenv("PRIMARY_MODEL",   "claude-sonnet-4-6")
SECONDARY_MODEL = os.getenv("SECONDARY_MODEL", "claude-haiku-4-5-20251001")
FALLBACK_MODEL  = os.getenv("FALLBACK_MODEL",  "gemini-2.5-pro")

# 모델별 단가 (USD per 1M tokens, 2025년 기준)
MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {
        "input":  3.0,
        "output": 15.0,
        "cache_write": 3.75,
        "cache_read":  0.30,
    },
    "claude-haiku-4-5-20251001": {
        "input":  0.80,
        "output": 4.0,
        "cache_write": 1.0,
        "cache_read":  0.08,
    },
    "claude-opus-4-7": {
        "input":  15.0,
        "output": 75.0,
        "cache_write": 18.75,
        "cache_read":  1.50,
    },
}


# ─────────────────────────────────────────────
# 데이터 클래스
# ─────────────────────────────────────────────

@dataclass
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    tool_calls: int = 0


@dataclass
class LLMResult:
    text: str
    model_used: str
    usage: LLMUsage
    cost_usd: float
    latency_ms: int
    raw: Any = None
    tool_results: list[dict] = field(default_factory=list)  # web search 결과


# ─────────────────────────────────────────────
# 비용 계산
# ─────────────────────────────────────────────

def calculate_cost(model: str, usage: LLMUsage) -> float:
    pricing = MODEL_PRICING.get(model, {"input": 3.0, "output": 15.0, "cache_write": 0, "cache_read": 0})
    cost = (
        usage.input_tokens * pricing["input"] / 1_000_000
        + usage.output_tokens * pricing["output"] / 1_000_000
        + usage.cache_creation_tokens * pricing.get("cache_write", 0) / 1_000_000
        + usage.cache_read_tokens * pricing.get("cache_read", 0) / 1_000_000
    )
    return round(cost, 6)


# ─────────────────────────────────────────────
# DB 로깅
# ─────────────────────────────────────────────

def log_ai_call(
    db_path: str,
    post_id: Optional[int],
    phase: str,
    model: str,
    usage: LLMUsage,
    cost_usd: float,
    latency_ms: int,
    success: bool,
    error: Optional[str] = None,
) -> None:
    try:
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            INSERT INTO ai_calls
              (post_id, phase, model, input_tokens, output_tokens,
               tool_calls, cost_usd, latency_ms, success, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                post_id, phase, model,
                usage.input_tokens, usage.output_tokens,
                usage.tool_calls, cost_usd, latency_ms,
                1 if success else 0, error,
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"  ⚠️  ai_calls 로깅 실패: {e}")


def append_ai_log(log_path: str, entry: dict) -> None:
    try:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        print(f"  ⚠️  ai_log.jsonl 기록 실패: {e}")


# ─────────────────────────────────────────────
# Claude 클라이언트
# ─────────────────────────────────────────────

class ClaudeClient:
    """Claude API 호출 (web search 도구 지원, prompt caching)."""

    def __init__(self) -> None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY가 .env에 설정되지 않았습니다.")
        self.client = anthropic.Anthropic(api_key=api_key)

    async def call(
        self,
        prompt: str,
        *,
        system: str = "",
        model: str = PRIMARY_MODEL,
        cache_system: bool = True,
        max_tokens: int = 8192,
        use_web_search: bool = False,
        temperature: float = 1.0,
    ) -> LLMResult:
        """Claude API 단건 호출. 동기 SDK를 asyncio executor에서 실행."""

        def _sync_call() -> tuple[Any, LLMUsage, list[dict]]:
            # 시스템 메시지 (prompt caching)
            system_blocks = []
            if system:
                system_blocks = [
                    {
                        "type": "text",
                        "text": system,
                        **({"cache_control": {"type": "ephemeral"}} if cache_system else {}),
                    }
                ]

            # 도구 설정
            tools = []
            if use_web_search:
                tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]

            kwargs: dict[str, Any] = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }
            if system_blocks:
                kwargs["system"] = system_blocks
            if tools:
                kwargs["tools"] = tools
            if temperature != 1.0:
                kwargs["temperature"] = temperature

            response = self.client.messages.create(**kwargs)

            # 사용량
            usage = LLMUsage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                cache_creation_tokens=getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
                cache_read_tokens=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
            )

            # 응답 텍스트 + tool_results 수집
            text_parts = []
            tool_results = []
            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "tool_use" and block.name == "web_search":
                    usage.tool_calls += 1
                elif block.type == "tool_result":
                    tool_results.append({"type": "tool_result", "content": str(block.content)})
                elif hasattr(block, "type") and "server_tool_use" in block.type:
                    usage.tool_calls += 1

            return response, usage, tool_results, "\n".join(text_parts)

        loop = asyncio.get_event_loop()
        response, usage, tool_results, text = await loop.run_in_executor(None, _sync_call)
        return response, usage, tool_results, text

    async def call_with_tools_agentic(
        self,
        prompt: str,
        *,
        system: str = "",
        model: str = PRIMARY_MODEL,
        cache_system: bool = True,
        max_tokens: int = 8192,
    ) -> tuple[str, LLMUsage, list[dict]]:
        """
        Web search 포함 agentic 루프 호출.
        Claude가 tool_use를 멈출 때까지 반복.
        Returns: (final_text, usage, web_findings)
        """
        def _sync_agentic() -> tuple[str, LLMUsage, list[dict]]:
            system_blocks = []
            if system:
                system_blocks = [
                    {
                        "type": "text",
                        "text": system,
                        **({"cache_control": {"type": "ephemeral"}} if cache_system else {}),
                    }
                ]

            tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]
            messages = [{"role": "user", "content": prompt}]

            total_usage = LLMUsage()
            web_findings = []
            final_text = ""

            for _ in range(10):  # max 10 turns
                response = self.client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system_blocks if system_blocks else anthropic.NOT_GIVEN,
                    tools=tools,
                    messages=messages,
                )

                # 누적 사용량
                total_usage.input_tokens += response.usage.input_tokens
                total_usage.output_tokens += response.usage.output_tokens
                total_usage.cache_creation_tokens += getattr(response.usage, "cache_creation_input_tokens", 0) or 0
                total_usage.cache_read_tokens += getattr(response.usage, "cache_read_input_tokens", 0) or 0

                # 응답 블록 처리
                assistant_content = []
                tool_use_blocks = []
                for block in response.content:
                    assistant_content.append(block)
                    if block.type == "text":
                        final_text = block.text
                    elif block.type == "tool_use":
                        total_usage.tool_calls += 1
                        tool_use_blocks.append(block)

                if response.stop_reason == "end_turn" or not tool_use_blocks:
                    break

                # tool_result 구성 (web_search 결과는 API가 자동으로 채움)
                messages.append({"role": "assistant", "content": assistant_content})
                tool_results_content = []
                for tu in tool_use_blocks:
                    tool_results_content.append({
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": "Search completed.",
                    })
                messages.append({"role": "user", "content": tool_results_content})

            return final_text, total_usage, web_findings

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync_agentic)


# ─────────────────────────────────────────────
# Gemini 클라이언트 (폴백)
# ─────────────────────────────────────────────

class GeminiClient:
    """Google Gemini API 폴백 클라이언트."""

    def __init__(self) -> None:
        from google import genai as google_genai
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY가 .env에 설정되지 않았습니다.")
        self.client = google_genai.Client(api_key=api_key)
        self.model = FALLBACK_MODEL

    async def call(self, prompt: str, *, system: str = "", max_tokens: int = 8192) -> tuple[str, LLMUsage]:
        def _sync_call() -> tuple[str, LLMUsage]:
            from google.genai import types as genai_types
            full_prompt = f"{system}\n\n{prompt}" if system else prompt
            response = self.client.models.generate_content(
                model=self.model,
                contents=full_prompt,
                config=genai_types.GenerateContentConfig(max_output_tokens=max_tokens),
            )
            text = response.text or ""
            usage = LLMUsage(
                input_tokens=getattr(response.usage_metadata, "prompt_token_count", 0) or 0,
                output_tokens=getattr(response.usage_metadata, "candidates_token_count", 0) or 0,
            )
            return text, usage

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync_call)


# ─────────────────────────────────────────────
# 메인 LLMClient
# ─────────────────────────────────────────────

class LLMClient:
    """
    LLM 추상 레이어.
    우선순위: primary(Claude Sonnet) → secondary(Claude Haiku) → fallback(Gemini).
    재시도: 429/5xx/timeout 시 exponential backoff (1s, 4s, 9s, max 3회).
    """

    BACKOFF_DELAYS = [1, 4, 9]  # seconds

    def __init__(self, db_path: str, log_path: Optional[str] = None) -> None:
        self.db_path = db_path
        self.log_path = log_path
        self._claude = None
        self._gemini = None

    def _get_claude(self) -> ClaudeClient:
        if self._claude is None:
            self._claude = ClaudeClient()
        return self._claude

    def _get_gemini(self) -> GeminiClient:
        if self._gemini is None:
            self._gemini = GeminiClient()
        return self._gemini

    def _is_retryable(self, exc: Exception) -> bool:
        err_str = str(exc).lower()
        return any(k in err_str for k in ("429", "529", "5xx", "500", "503", "timeout", "rate_limit", "overloaded"))

    async def acall(
        self,
        prompt: str,
        *,
        system: str = "",
        model_hint: str = "primary",   # primary | secondary | heavy
        max_tokens: int = 8192,
        use_web_search: bool = False,
        post_id: Optional[int] = None,
        phase: str = "unknown",
        cache_system: bool = True,
    ) -> LLMResult:
        """
        메인 호출 인터페이스.
        model_hint에 따라 모델 순서를 결정하고, 실패 시 다음 모델로 폴백.
        """
        if model_hint == "secondary":
            model_sequence = [SECONDARY_MODEL, PRIMARY_MODEL, None]
        elif model_hint == "heavy":
            heavy = os.getenv("HEAVY_MODEL", "claude-opus-4-7")
            model_sequence = [heavy, PRIMARY_MODEL, None]
        else:
            model_sequence = [PRIMARY_MODEL, SECONDARY_MODEL, None]

        last_error: Optional[Exception] = None

        for model in model_sequence:
            # None = Gemini 폴백
            if model is None:
                try:
                    return await self._call_gemini(prompt, system=system, max_tokens=max_tokens,
                                                   post_id=post_id, phase=phase)
                except Exception as e:
                    raise RuntimeError(f"모든 모델 실패. 마지막 오류: {e}") from e

            # Claude 호출 (재시도 포함)
            for attempt, delay in enumerate(self.BACKOFF_DELAYS + [None], start=1):
                t0 = time.monotonic()
                try:
                    result = await self._call_claude(
                        prompt, system=system, model=model,
                        max_tokens=max_tokens, use_web_search=use_web_search,
                        post_id=post_id, phase=phase, cache_system=cache_system,
                    )
                    return result
                except anthropic.RateLimitError as e:
                    last_error = e
                    print(f"  ⚠️  {model} RateLimit (attempt {attempt})")
                except anthropic.APIStatusError as e:
                    if e.status_code >= 500:
                        last_error = e
                        print(f"  ⚠️  {model} {e.status_code} (attempt {attempt})")
                    else:
                        raise  # 4xx는 재시도 안 함
                except Exception as e:
                    if self._is_retryable(e):
                        last_error = e
                        print(f"  ⚠️  {model} 오류 (attempt {attempt}): {e}")
                    else:
                        raise

                if delay is None:
                    print(f"  ❌ {model} 최대 재시도 초과 → 다음 모델로")
                    break
                print(f"  ⏳ {delay}초 후 재시도...")
                await asyncio.sleep(delay)

        raise RuntimeError(f"모든 모델 실패. 마지막 오류: {last_error}")

    async def acall_research(
        self,
        prompt: str,
        *,
        system: str = "",
        model_hint: str = "primary",
        max_tokens: int = 8192,
        post_id: Optional[int] = None,
        cache_system: bool = True,
    ) -> LLMResult:
        """Research 전용: web search 도구 포함 agentic 루프 호출."""
        model = PRIMARY_MODEL if model_hint != "secondary" else SECONDARY_MODEL
        t0 = time.monotonic()
        try:
            claude = self._get_claude()
            text, usage, web_findings = await claude.call_with_tools_agentic(
                prompt, system=system, model=model,
                cache_system=cache_system, max_tokens=max_tokens,
            )
            latency_ms = int((time.monotonic() - t0) * 1000)
            cost = calculate_cost(model, usage)

            result = LLMResult(
                text=text,
                model_used=model,
                usage=usage,
                cost_usd=cost,
                latency_ms=latency_ms,
                raw=None,
                tool_results=web_findings,
            )
            log_ai_call(self.db_path, post_id, "research", model, usage, cost, latency_ms, True)
            if self.log_path:
                append_ai_log(self.log_path, {
                    "phase": "research", "model": model,
                    "usage": usage.__dict__, "cost_usd": cost,
                    "latency_ms": latency_ms, "ts": datetime.now(timezone.utc).isoformat(),
                })
            return result
        except Exception as e:
            latency_ms = int((time.monotonic() - t0) * 1000)
            empty_usage = LLMUsage()
            log_ai_call(self.db_path, post_id, "research", model, empty_usage, 0, latency_ms, False, str(e))
            raise

    async def _call_claude(
        self,
        prompt: str,
        *,
        system: str,
        model: str,
        max_tokens: int,
        use_web_search: bool,
        post_id: Optional[int],
        phase: str,
        cache_system: bool,
    ) -> LLMResult:
        t0 = time.monotonic()
        claude = self._get_claude()
        response, usage, tool_results, text = await claude.call(
            prompt, system=system, model=model,
            cache_system=cache_system, max_tokens=max_tokens,
            use_web_search=use_web_search,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        cost = calculate_cost(model, usage)

        log_ai_call(self.db_path, post_id, phase, model, usage, cost, latency_ms, True)
        if self.log_path:
            append_ai_log(self.log_path, {
                "phase": phase, "model": model,
                "prompt_len": len(prompt), "text_len": len(text),
                "usage": usage.__dict__, "cost_usd": cost,
                "latency_ms": latency_ms, "ts": datetime.now(timezone.utc).isoformat(),
            })

        return LLMResult(
            text=text,
            model_used=model,
            usage=usage,
            cost_usd=cost,
            latency_ms=latency_ms,
            raw=response,
            tool_results=tool_results,
        )

    async def _call_gemini(
        self,
        prompt: str,
        *,
        system: str,
        max_tokens: int,
        post_id: Optional[int],
        phase: str,
    ) -> LLMResult:
        t0 = time.monotonic()
        gemini = self._get_gemini()
        text, usage = await gemini.call(prompt, system=system, max_tokens=max_tokens)
        latency_ms = int((time.monotonic() - t0) * 1000)
        cost = round(usage.input_tokens * 1.25 / 1_000_000 + usage.output_tokens * 10.0 / 1_000_000, 6)

        print(f"  🔄 Gemini 폴백 사용 (phase={phase})")
        log_ai_call(self.db_path, post_id, phase, FALLBACK_MODEL, usage, cost, latency_ms, True)
        if self.log_path:
            append_ai_log(self.log_path, {
                "phase": phase, "model": FALLBACK_MODEL,
                "usage": usage.__dict__, "cost_usd": cost,
                "latency_ms": latency_ms, "ts": datetime.now(timezone.utc).isoformat(),
            })

        return LLMResult(
            text=text,
            model_used=FALLBACK_MODEL,
            usage=usage,
            cost_usd=cost,
            latency_ms=latency_ms,
        )
