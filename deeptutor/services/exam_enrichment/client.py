"""Catalog-selected OpenAI-compatible client for exam enrichment.

Credentials stay inside DeepTutor's model catalog and LLM client. This module
only resolves a profile into an in-memory ``LLMConfig`` and never logs or
returns API keys.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import json
from typing import Any

from deeptutor.services.config.model_catalog import ModelCatalogService, get_model_catalog_service
from deeptutor.services.llm.client import LLMClient
from deeptutor.services.llm.config import LLMConfig, get_llm_config

from .models import EnrichmentPayload
from .prompts import SYSTEM_PROMPT, response_format

CompletionCallable = Callable[..., Awaitable[str]]


class ExamEnrichmentClient:
    """Use an explicit ModelCatalog profile with DeepTutor's LLM client.

    ``profile_id`` selects credentials, endpoint, headers, and binding from
    ``services.llm.profiles``. ``provider`` and ``model`` are optional routing
    overrides; neither requires nor exposes a key. Without a profile ID, the
    current DeepTutor LLM configuration remains a backward-compatible fallback.
    """

    def __init__(
        self,
        *,
        profile_id: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        completion: CompletionCallable | None = None,
        catalog_service: ModelCatalogService | None = None,
    ) -> None:
        self.profile_id = profile_id
        self.provider = provider
        self.model = model
        self._completion = completion
        self._catalog_service = catalog_service
        self._config: LLMConfig | None = None

    def _resolve_config(self) -> LLMConfig:
        if self._config is not None:
            return self._config
        if not self.profile_id:
            current = get_llm_config()
            self._config = current.model_copy(
                {
                    "model": self.model or current.model,
                    "binding": self.provider or current.binding,
                    "provider_name": self.provider or current.provider_name,
                }
            )
            return self._config

        catalog_service = self._catalog_service or get_model_catalog_service()
        catalog = catalog_service.load()
        service = catalog.get("services", {}).get("llm", {})
        profiles = service.get("profiles", [])
        profile = next(
            (
                item
                for item in profiles
                if isinstance(item, dict) and item.get("id") == self.profile_id
            ),
            None,
        )
        if profile is None:
            raise ValueError(f"LLM profile {self.profile_id!r} was not found in the model catalog")

        selected_model = self.model or self._profile_default_model(profile, service)
        if not selected_model:
            raise ValueError(f"LLM profile {self.profile_id!r} has no usable model")
        binding = str(self.provider or profile.get("binding") or "openai")
        self._config = LLMConfig(
            model=selected_model,
            api_key=str(profile.get("api_key") or ""),
            base_url=str(profile.get("base_url") or "") or None,
            effective_url=str(profile.get("base_url") or "") or None,
            binding=binding,
            provider_name=binding,
            api_version=str(profile.get("api_version") or "") or None,
            extra_headers=dict(profile.get("extra_headers") or {}),
            temperature=0.0,
            max_tokens=1_500,
        )
        return self._config

    @staticmethod
    def _profile_default_model(profile: dict[str, Any], service: dict[str, Any]) -> str:
        models = [item for item in profile.get("models", []) if isinstance(item, dict)]
        active_id = service.get("active_model_id")
        active = next((item for item in models if item.get("id") == active_id), None)
        chosen = active or (models[0] if models else {})
        return str(chosen.get("model") or "")

    def resolved_provider_and_model(self) -> tuple[str, str]:
        """Return safe provenance labels without exposing credential data."""
        config = self._resolve_config()
        return config.provider_name or config.binding or "configured", config.model

    async def enrich(self, prompt: str) -> EnrichmentPayload:
        """Submit one prompt and strictly validate the returned JSON payload."""
        config = self._resolve_config()
        if self._completion is not None:
            text = await self._completion(
                prompt=prompt,
                system_prompt=SYSTEM_PROMPT,
                model=config.model,
                binding=config.binding,
                max_retries=0,
                temperature=0.0,
                max_tokens=1_500,
                response_format=response_format(),
            )
        else:
            # LLMClient delegates to DeepTutor's provider catalog/factory. For
            # an OpenAI-compatible profile it uses the selected base URL and
            # profile-only headers, rather than the unrelated active profile.
            text = await LLMClient(config).complete(
                prompt,
                system_prompt=SYSTEM_PROMPT,
                max_retries=0,
                temperature=0.0,
                max_tokens=1_500,
                response_format=response_format(),
            )
        try:
            return EnrichmentPayload.model_validate_json(text)
        except (json.JSONDecodeError, ValueError) as exc:
            preview = text[:160].replace("\n", " ")
            raise ValueError(
                f"Provider response did not match exam enrichment schema: {preview!r}"
            ) from exc
