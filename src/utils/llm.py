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
from langchain_core.outputs import ChatResult, ChatGeneration, LLMResult
from langchain_core.callbacks import BaseCallbackHandler, CallbackManagerForLLMRun
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
        # An unpriced model contributes nothing, rather than being billed at gpt-4o
        # rates. Defaulting priced a local run at 12.50 USD per 2M tokens — a
        # fabricated figure that reads as plausible in a cost column. score_run.py
        # already skips unknown models; this now matches it.
        costs = _MODEL_COSTS.get(model)
        cost = input_tokens * costs["input"] + output_tokens * costs["output"] if costs else 0.0
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


class _UsageCallback(BaseCallbackHandler):
    """Feed every OpenAI-compatible completion into the cost tracker.

    record() used to be reachable only from AzureAIFoundryChatModel, so the
    llmCost block in every TTE report was a structural zero — one artifact on
    disk shows $0.00 and 0 calls against 137 real billed OpenRouter calls. The
    model recorded is the one the provider says it *served* (llm_output's
    model_name comes from the response body), not the one that was requested;
    those two disagree in exactly the cases worth catching.
    """

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        output = response.llm_output or {}
        usage = output.get("token_usage") or {}
        get_cost_tracker().record(
            output.get("model_name") or "unknown",
            usage.get("prompt_tokens") or 0,
            usage.get("completion_tokens") or 0,
        )


_USAGE_CALLBACK = _UsageCallback()


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

# Plain-text preambles, for models that reason without tagging it. Measured on
# Qwen/Qwen3.5-4B, which answers "Return ONLY: {"a":1}" with 1232 characters
# beginning "Thinking Process:\n\n1.  **Analyze the Request:**". There is no
# <think> tag to strip, so the tag regex leaves the whole thing intact.
_PREAMBLE_MARKER = re.compile(
    r"^\s*(?:thinking process|reasoning|let me think|thought process|analysis)\s*[:\n]",
    re.IGNORECASE,
)

# Innermost {...} / [...] runs. Deliberately non-recursive: it is a detector for
# "is there JSON in here", and the last match is what matters, not the parse.
_JSON_RUN = re.compile(r"\{[^{}]*\}|\[[^\[\]]*\]", re.DOTALL)


def extract_answer(content: str) -> tuple[str, str]:
    """Return (cleaned, strategy) for one model response.

    Three strategies, tried in order, with the name returned so a caller can log
    which one fired. Knowing that matters: if a benchmark records a model as
    unable to hold an output schema, the reader has to be able to tell that from
    "our preprocessing did not know that model's reasoning format".

    - ``think_tag``  — a <think>…</think> block was removed. Qwen3-8B/hari.
    - ``last_json``  — no tag, but the text opens with a prose reasoning preamble
      and contains JSON. The **last** run is taken, not the first: the reasoning
      quotes the prompt, so an answer of ``{"a":1}`` arrives with nine balanced
      JSON runs ahead of it and "first brace wins" picks the echoed input.
    - ``none``       — returned unchanged. Free-text callers must not be touched.

    Detection rather than a per-model table on purpose. A table would need an
    entry for every model, and the entries for models nobody has measured would
    be guesses — which is how a tooling gap gets recorded as a model defect.
    """
    if _THINK_BLOCK.search(content):
        return _THINK_BLOCK.sub("", content).strip(), "think_tag"

    if _PREAMBLE_MARKER.match(content):
        runs = _JSON_RUN.findall(content)
        if runs:
            return runs[-1].strip(), "last_json"

    return content, "none"


class ReasoningStrippedChatModel(BaseChatModel):
    """Wraps a chat model that may narrate its reasoning before answering.

    Every caller in this codebase feeds the response straight into a JSON parser —
    four of them through LangChain's JsonOutputParser in a `prompt | llm | parser`
    chain, where there is no seam to clean the text. Stripping per call site means
    one is always missed; stripping here means switching LLM_MODEL to a reasoning
    model cannot silently break parsing downstream.

    Reasoning arrives in at least two shapes, and the difference is not cosmetic:
    Qwen3-8B tags it, Qwen3.5-4B does not. `/no_think` asks for neither; both
    models emit one anyway. See ``extract_answer`` for how each is handled and why
    detection is preferred to a per-model table.
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
                cleaned, strategy = extract_answer(content)
                generation.message.content = cleaned
                if strategy != "none":
                    generation.message.response_metadata.setdefault(
                        "reasoning_strategy", strategy
                    )
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
    json_mode: bool = False,
    max_tokens: int | None = None,
) -> BaseChatModel:
    """
    Returns a configured Chat Model instance.

    Temperature and seed are controlled via LLM_TEMPERATURE and LLM_SEED env vars.
    response_format: optional, e.g. {"type": "json_object"} to enforce JSON output.

    json_mode: constrain a *local* model to emit a JSON object. Reasoning models
    narrate before answering, and unbounded narration is not a parsing problem —
    it is a throughput one. Measured on Qwen3.5-4B against one concept-selection
    prompt:

        unconstrained          did not finish inside 900s
        max_tokens=200         37.2s, truncated mid-narration, no JSON at all
        response_format json    8.8s, 44 tokens, exactly the schema

    ``extract_answer`` recovers the answer when narration happens; this stops it
    happening. Both are needed: the strip covers calls that cannot constrain
    (prose), the constraint covers the ones that would otherwise cost minutes.

    Local-only on purpose. OpenAI rejects json_object unless the prompt itself
    mentions JSON, and three call sites here parse JSON from prompts that never
    say the word — enabling it for remote providers would turn those into 400s.
    vLLM has no such rule (verified against the running server).

    Priority:
    0. vLLM (model has a 'vllm/' prefix) — always wins on prefix match; raises if
       VLLM_BASE_URL is unset rather than falling through to a remote provider
    1. Azure AI Foundry (if AZURE_API_KEY and AZURE_ENDPOINT are set)
    2. OpenRouter (if OPENROUTER_API_KEY is set)
    3. Google Gemini (if GOOGLE_API_KEY is set and model contains 'gemini')
    4. OpenAI (if OPENAI_API_KEY is set)
    """
    model = model_name or settings.LLM_MODEL
    temp = temperature if temperature is not None else settings.LLM_TEMPERATURE
    seed = settings.LLM_SEED

    # Option 0: vLLM — prefix-based routing always wins (before any credential-based provider)
    if _is_vllm_model(model):
        # Never fall through. Without this the prefix is a request that gets
        # quietly declined: `vllm/x` reaches OpenRouter as the literal string
        # "vllm/x", or is rewritten to gpt-4o-mini by Option 4. Both produce real
        # completions from a remote provider under a local model's label.
        if not settings.VLLM_BASE_URL:
            raise LLMConfigurationError(
                f"Model {model!r} is prefixed 'vllm/' but VLLM_BASE_URL is not set. "
                "Set VLLM_BASE_URL, or use a model name without the prefix if a "
                "remote provider is intended."
            )
        actual_model = _strip_vllm_prefix(model)
        seed_kwargs: dict = {"seed": seed} if seed is not None else {}

        # Suppress the reasoning block at the template level, which is the only
        # channel that works. _with_no_think appends "/no_think" to the prompt;
        # both models measured ignore it, because a prompt string is a request.
        # A qwen3-family chat template carries
        #     {%- if enable_thinking is defined and enable_thinking is false %}
        #         {{- '<think>\n\n</think>\n\n' }}
        # which pre-fills a CLOSED think block into the assistant turn -- forced
        # prefix text rather than an instruction.
        #
        # This is not a cost optimisation. snuh/hari-q3-8b never emitted a stop
        # token and vLLM cut it at the ceiling: 16,384 max_model_len minus a 1,450
        # token prompt is exactly the 14,934 tokens it "produced", finish_reason
        # "length". A truncated response cannot parse, so every critic call fell
        # into critic.py's handler and returned seed_concept_ids -- a whole
        # benchmark ran with Agent 2's KG expansion discarded, looking like a
        # slow model rather than a disabled stage. Templates without the switch
        # ignore the kwarg.
        # extra_body, not a bare model_kwargs key. langchain-openai forwards
        # model_kwargs verbatim into Completions.create(), which has no **kwargs, so
        # a flat "chat_template_kwargs" raised
        #     Completions.create() got an unexpected keyword argument
        # on every reranker and critic call -- 106 of them in one benchmark run,
        # each swallowed by a handler that fell back to top-1. extra_body is the
        # documented channel for vLLM-only request fields.
        seed_kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}

        effective_format = response_format or ({"type": "json_object"} if json_mode else None)
        if effective_format:
            seed_kwargs["response_format"] = effective_format

        # max_tokens is a DECLARED ChatOpenAI field, so routing it through
        # model_kwargs raises ValidationError at construction rather than warning
        # the way an undeclared key like `seed` does. ConceptCritic passes 4096, so
        # that made the class impossible to instantiate on the vLLM path.
        extra_model_args: dict = {}
        if max_tokens is not None:
            extra_model_args["max_tokens"] = max_tokens
        return ReasoningStrippedChatModel(
            inner=ChatOpenAI(
                model=actual_model,
                api_key=settings.VLLM_API_KEY or "EMPTY",
                base_url=settings.VLLM_BASE_URL,
                temperature=temp,
                model_kwargs=seed_kwargs,
                **extra_model_args,
            ),
            callbacks=[_USAGE_CALLBACK],
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
            callbacks=[_USAGE_CALLBACK],
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
        # No substitution: an unknown id gets the provider's 404. Rewriting it to
        # gpt-4o-mini answered every request successfully with the wrong model and
        # logged nothing.
        return ChatOpenAI(
            model=model,
            api_key=settings.OPENAI_API_KEY,
            temperature=temp,
            model_kwargs=seed_kwargs,
            callbacks=[_USAGE_CALLBACK],
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
