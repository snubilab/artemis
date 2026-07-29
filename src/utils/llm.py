"""
LLM utility for ARTEMIS 3.1.
Supports Azure AI Foundry (priority), OpenRouter, Google Gemini, and OpenAI.
"""
import re
import threading
from typing import Any, List, Optional

from openai import OpenAI
from langchain_openai import ChatOpenAI
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatResult, ChatGeneration
from langchain_core.callbacks import CallbackManagerForLLMRun
from src.settings import settings
from src.utils.exceptions import LLMConfigurationError

# Azure pricing (per token, USD)
_MODEL_COSTS: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 2.5e-6, "output": 1.0e-5},
    "gpt-4o-mini": {"input": 1.65e-7, "output": 6.6e-7},
}


class LLMCostTracker:
    """Thread-safe accumulator for LLM token usage and cost."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls: int = 0
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self.cost_usd: float = 0.0

    def record(self, model: str, input_tokens: int, output_tokens: int) -> None:
        costs = _MODEL_COSTS.get(model, _MODEL_COSTS["gpt-4o"])
        cost = input_tokens * costs["input"] + output_tokens * costs["output"]
        with self._lock:
            self.calls += 1
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens
            self.cost_usd += cost

    def summary(self) -> dict[str, Any]:
        with self._lock:
            return {
                "llm_calls": self.calls,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_tokens": self.input_tokens + self.output_tokens,
                "cost_usd": round(self.cost_usd, 6),
            }

    def reset(self) -> None:
        with self._lock:
            self.calls = 0
            self.input_tokens = 0
            self.output_tokens = 0
            self.cost_usd = 0.0


_cost_tracker = LLMCostTracker()


def get_cost_tracker() -> LLMCostTracker:
    """Return the global LLM cost tracker singleton."""
    return _cost_tracker


class AzureAIFoundryChatModel(BaseChatModel):
    """LangChain wrapper for Azure AI Foundry using openai.OpenAI SDK with base_url."""

    client: Any = None
    model: str = "gpt-4o"
    temperature: float = 0.0
    response_format: dict | None = None

    def __init__(self, endpoint: str, api_key: str, model: str = "gpt-4o", temperature: float = 0.0, response_format: dict | None = None, **kwargs):
        super().__init__(**kwargs)
        self.model = model
        self.temperature = temperature
        self.response_format = response_format
        # Azure AI Foundry uses standard OpenAI SDK with base_url
        self.client = OpenAI(
            base_url=endpoint,
            api_key=api_key,
            timeout=120,  # Prevent indefinite blocking
        )
    
    @property
    def _llm_type(self) -> str:
        return "azure-ai-foundry"
    
    def _convert_messages(self, messages: List[BaseMessage]) -> List[dict]:
        """Convert LangChain messages to OpenAI format."""
        result = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                result.append({"role": "system", "content": msg.content})
            elif isinstance(msg, HumanMessage):
                result.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                result.append({"role": "assistant", "content": msg.content})
            else:
                result.append({"role": "user", "content": str(msg.content)})
        return result
    
    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Generate chat completion using OpenAI SDK."""
        openai_messages = self._convert_messages(messages)
        
        extra_kwargs: dict = {}
        if self.response_format:
            extra_kwargs["response_format"] = self.response_format
        response = self.client.chat.completions.create(
            model=self.model,
            messages=openai_messages,
            temperature=self.temperature,
            seed=settings.LLM_SEED,
            stop=stop,
            timeout=120,
            **extra_kwargs,
            **kwargs,
        )

        if response.usage:
            get_cost_tracker().record(
                self.model,
                response.usage.prompt_tokens or 0,
                response.usage.completion_tokens or 0,
            )

        content = response.choices[0].message.content or ""
        message = AIMessage(content=content)
        generation = ChatGeneration(message=message)
        
        return ChatResult(generations=[generation])


def resolve_model(override: str | None = None) -> str:
    """The model a call site will actually use.

    Call sites that need the model *name* — for a cache key, a log line, a
    provenance record — must ask here rather than hardcoding one, or changing
    LLM_MODEL moves the pipeline while leaving them behind. That has already
    happened three times in this codebase: the comparator pinned its own vLLM
    model, the Agent 2 critic returned a literal "gpt-4o-mini" for the three
    commonest OMOP domains, and the classifier defaulted to a specific 8B model.
    Each looked local and harmless; together they meant no single setting could
    move the pipeline, and a benchmark labelled with one model would have been
    mostly executed by another.
    """
    return override or settings.LLM_MODEL


def _is_vllm_model(model: str) -> bool:
    return model.startswith("vllm/")


def _strip_vllm_prefix(model: str) -> str:
    return model[5:] if model.startswith("vllm/") else model


_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)


class ReasoningStrippedChatModel(BaseChatModel):
    """Wraps a chat model whose output may carry a <think>…</think> preamble.

    Qwen3-class models emit chain-of-thought before the answer. Every caller in
    this codebase feeds the response straight into a JSON parser — four of them
    through LangChain's JsonOutputParser in a `prompt | llm | parser` chain,
    where there is no seam to clean the text. Stripping per call site means one
    of them is always missed; stripping here means switching LLM_MODEL to a
    reasoning model cannot silently break parsing downstream.

    `/no_think` asks the model to skip the block; the regex handles the case
    where it emits one anyway.
    """

    inner: BaseChatModel

    @property
    def _llm_type(self) -> str:
        return f"reasoning-stripped-{self.inner._llm_type}"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        result = self.inner._generate(self._with_no_think(messages), stop, run_manager, **kwargs)
        for generation in result.generations:
            content = generation.message.content
            if isinstance(content, str):
                generation.message.content = _THINK_BLOCK.sub("", content).strip()
        return result

    @staticmethod
    def _with_no_think(messages: List[BaseMessage]) -> List[BaseMessage]:
        """Append the directive to the last human turn, where the model reads it."""
        if not messages:
            return messages
        last = messages[-1]
        if not isinstance(last, HumanMessage) or not isinstance(last.content, str):
            return messages
        if last.content.rstrip().endswith("/no_think"):
            return messages
        return [*messages[:-1], HumanMessage(content=f"{last.content}\n/no_think")]


def get_llm(
    model_name: str | None = None,
    temperature: float | None = None,
    response_format: dict | None = None,
) -> BaseChatModel:
    """
    Returns a configured Chat Model instance.

    Temperature and seed are controlled via LLM_TEMPERATURE and LLM_SEED env vars.
    response_format: optional, e.g. {"type": "json_object"} to enforce JSON output.

    Priority:
    0. vLLM (if model has 'vllm/' prefix and VLLM_BASE_URL is set) — always wins on prefix match
    1. Azure AI Foundry (if AZURE_API_KEY and AZURE_ENDPOINT are set)
    2. OpenRouter (if OPENROUTER_API_KEY is set)
    3. Google Gemini (if GOOGLE_API_KEY is set and model contains 'gemini')
    4. OpenAI (if OPENAI_API_KEY is set)
    """
    model = model_name or settings.LLM_MODEL
    temp = temperature if temperature is not None else settings.LLM_TEMPERATURE
    seed = settings.LLM_SEED

    # Option 0: vLLM — prefix-based routing always wins (before any credential-based provider)
    if _is_vllm_model(model) and settings.VLLM_BASE_URL:
        actual_model = _strip_vllm_prefix(model)
        seed_kwargs: dict = {"seed": seed} if seed is not None else {}
        if response_format:
            seed_kwargs["response_format"] = response_format
        return ReasoningStrippedChatModel(
            inner=ChatOpenAI(
                model=actual_model,
                api_key=settings.VLLM_API_KEY or "EMPTY",
                base_url=settings.VLLM_BASE_URL,
                temperature=temp,
                model_kwargs=seed_kwargs,
            )
        )

    # Option 1: Azure AI Foundry (priority - using openai.OpenAI SDK with base_url)
    if settings.AZURE_API_KEY and settings.AZURE_ENDPOINT:
        return AzureAIFoundryChatModel(
            endpoint=settings.AZURE_ENDPOINT,
            api_key=settings.AZURE_API_KEY,
            model=model,
            temperature=temp,
            response_format=response_format,
        )

    # Seed kwargs for OpenAI-compatible APIs
    seed_kwargs = {"seed": seed} if seed is not None else {}
    if response_format:
        seed_kwargs["response_format"] = response_format

    # Option 2: OpenRouter (recommended for multi-model access)
    if settings.OPENROUTER_API_KEY:
        return ChatOpenAI(
            model=model,
            api_key=settings.OPENROUTER_API_KEY,
            base_url=settings.OPENROUTER_BASE_URL,
            temperature=temp,
            model_kwargs=seed_kwargs,
            default_headers={
                "HTTP-Referer": "https://artemis.ai",
                "X-Title": "ARTEMIS 3.1"
            }
        )
    
    # Option 3: Google Gemini (direct)
    if "gemini" in model and settings.GOOGLE_API_KEY:
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=settings.GOOGLE_API_KEY,
            temperature=temp,
            convert_system_message_to_human=True 
        )
    
    # Option 4: OpenAI (direct)
    if settings.OPENAI_API_KEY:
        return ChatOpenAI(
            model=model if "gpt" in model else "gpt-4o-mini",
            api_key=settings.OPENAI_API_KEY,
            temperature=temp,
            model_kwargs=seed_kwargs,
        )
    
    # No API key configured
    raise LLMConfigurationError(
        "No LLM API key configured. Set one of: "
        "AZURE_API_KEY + AZURE_ENDPOINT (priority), OPENROUTER_API_KEY, "
        "GOOGLE_API_KEY, or OPENAI_API_KEY in your .env file."
    )


_models_cache: list[dict[str, str]] | None = None
_models_cache_ts: float = 0.0
_MODELS_CACHE_TTL: float = 300.0  # 5 minutes


async def list_available_models() -> list[dict[str, str]]:
    """Return list of available LLM models based on configured providers.

    Results are cached for 5 minutes to avoid repeated HTTP calls to vLLM.
    """
    import time

    import httpx

    global _models_cache, _models_cache_ts  # noqa: PLW0603

    now = time.monotonic()
    if _models_cache is not None and (now - _models_cache_ts) < _MODELS_CACHE_TTL:
        return _models_cache

    models: list[dict[str, str]] = []

    if settings.AZURE_API_KEY and settings.AZURE_ENDPOINT:
        models.append({"id": "gpt-4o", "name": "GPT-4o (Azure)", "provider": "azure"})
        models.append({"id": "gpt-4o-mini", "name": "GPT-4o Mini (Azure)", "provider": "azure"})

    if settings.OPENROUTER_API_KEY:
        models.append({"id": "gpt-4o", "name": "GPT-4o (OpenRouter)", "provider": "openrouter"})
        models.append({"id": "gpt-4o-mini", "name": "GPT-4o Mini (OpenRouter)", "provider": "openrouter"})

    if settings.OPENAI_API_KEY:
        models.append({"id": "gpt-4o", "name": "GPT-4o", "provider": "openai"})
        models.append({"id": "gpt-4o-mini", "name": "GPT-4o Mini", "provider": "openai"})

    if settings.VLLM_BASE_URL:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{settings.VLLM_BASE_URL}/models",
                    timeout=2.0,
                    headers={"Authorization": f"Bearer {settings.VLLM_API_KEY or 'EMPTY'}"},
                )
            resp.raise_for_status()
            data = resp.json()
            for m in data.get("data", []):
                model_id = m.get("id", "")
                if model_id:
                    models.append({
                        "id": f"vllm/{model_id}",
                        "name": f"{model_id} (vLLM)",
                        "provider": "vllm",
                    })
        except Exception:
            pass  # vLLM unavailable — skip silently

    _models_cache = models
    _models_cache_ts = now
    return models
