"""The LLM side: configuration, the Pydantic AI agent, and a safe `explain_finding`.

Why Pydantic AI?
    It gives us three things we would otherwise write by hand:
      1. structured output: the model must return our `Explanation` class, validated;
      2. automatic retry: if validation (or our grounding check) fails, the model is told
         what was wrong and asked again;
      3. one interface for many providers: we talk to any OpenAI-compatible endpoint, which
         is what Ollama, vLLM, LM Studio, Azure OpenAI and most customer gateways offer.

Settings (environment variables or `.env`), so the same code runs on your laptop and on a
customer's own LLM:

    LLM_BASE_URL     default http://localhost:11434/v1   (Ollama)
    LLM_MODEL        default qwen2.5:7b
    LLM_API_KEY      default "ollama" (local servers ignore it)
    LLM_OUTPUT_MODE  "prompted" (default: model writes JSON as text, works with any chat model)
                     or "tool" (uses function calling, needs a model/server that supports it)
    LLM_TIMEOUT      seconds per request, default 180
"""

from __future__ import annotations

import os
from typing import Literal

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")  # keep the command line output clean

from pydantic import BaseModel
from pydantic_ai import Agent, ModelRetry, PromptedOutput, RunContext
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings

from ..rules.model import Finding
from ..settings import load_settings, use_system_certificates
from .grounding import grounding_problems
from .prompt import SYSTEM_PROMPT, build_prompt
from .schema import Explanation

DEFAULT_BASE_URL = "http://localhost:11434/v1"
DEFAULT_MODEL = "qwen2.5:7b"


class LlmConfig(BaseModel):
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    api_key: str = "ollama"
    output_mode: Literal["prompted", "tool"] = "prompted"
    timeout: float = 180.0
    retries: int = 2

    @classmethod
    def from_env(cls) -> "LlmConfig":
        load_settings()
        env = os.environ.get
        return cls(
            base_url=env("LLM_BASE_URL", DEFAULT_BASE_URL),
            model=env("LLM_MODEL", DEFAULT_MODEL),
            api_key=env("LLM_API_KEY", "ollama"),
            output_mode=env("LLM_OUTPUT_MODE", "prompted"),  # type: ignore[arg-type]
            timeout=float(env("LLM_TIMEOUT", "180")),
        )

    def public(self) -> dict:
        """What goes into reports. Never the API key."""
        return {"base_url": self.base_url, "model": self.model, "output_mode": self.output_mode}


def build_model(cfg: LlmConfig) -> Model:
    use_system_certificates()  # company TLS inspection, see settings.py
    return OpenAIChatModel(cfg.model, provider=OpenAIProvider(base_url=cfg.base_url, api_key=cfg.api_key))


def build_agent(model: Model | str, cfg: LlmConfig | None = None) -> Agent[Finding, Explanation]:
    cfg = cfg or LlmConfig()
    output = PromptedOutput(Explanation) if cfg.output_mode == "prompted" else Explanation
    agent: Agent[Finding, Explanation] = Agent(
        model, deps_type=Finding, output_type=output, instructions=SYSTEM_PROMPT,
        retries=cfg.retries, model_settings=ModelSettings(timeout=cfg.timeout, temperature=0),
    )

    @agent.output_validator
    def check_grounding(ctx: RunContext[Finding], answer: Explanation) -> Explanation:
        problems = grounding_problems(answer, ctx.deps)
        if problems:
            # The text of this error is sent back to the model so it can correct itself.
            raise ModelRetry(
                "Your answer mentions things that are not in the finding: "
                + "; ".join(problems) + ". Use only names, addresses and evidence from the finding."
            )
        return answer

    return agent


class ExplainResult(BaseModel):
    explanation: Explanation | None = None
    error: str | None = None  # why there is no explanation
    unreachable: bool = False  # True if the LLM server could not be reached at all


def explain_finding(agent: Agent[Finding, Explanation], finding: Finding) -> ExplainResult:
    """Ask the LLM to explain one finding. Never raises: the finding stays valid without it."""
    try:
        run = agent.run_sync(build_prompt(finding), deps=finding)
        return ExplainResult(explanation=run.output)
    except Exception as e:  # advisory feature: any failure only means "no explanation"
        name = type(e).__name__
        unreachable = any(k in name or k in repr(e) for k in ("ConnectError", "ConnectionError", "APIConnectionError"))
        return ExplainResult(error=f"{name}: {str(e)[:300]}", unreachable=unreachable)
