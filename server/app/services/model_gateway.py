from __future__ import annotations

import json
import os
import re
import time
import uuid
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from server.app.core.config import ModelRoute, Settings
from server.app.core.errors import AppError
from server.app.models.job import utc_now_iso
from server.app.services.contracts import canonical_json
from server.app.services.storage import JobStorage, sha256_text
from server.app.services.task_registry import TaskRegistry, TaskSpec


class ModelGatewayError(AppError):
    pass


@dataclass(frozen=True)
class ProviderResult:
    payload: dict[str, Any]
    provider_call_id: str | None
    usage: dict[str, Any]
    attempts: int = 1
    normalizations: tuple[str, ...] = ()


class ModelGateway:
    def __init__(self, settings: Settings, storage: JobStorage | None = None) -> None:
        self.settings = settings
        self.storage = storage
        self.registry = TaskRegistry(settings)

    def route_for_task(self, task: str) -> ModelRoute:
        try:
            return self.registry.route(task)
        except AppError as exc:
            raise ModelGatewayError(
                exc.code,
                exc.message,
                retryable=exc.retryable,
                status_code=exc.status_code,
                diagnostics=exc.diagnostics,
            ) from exc

    def validate_required_routes(self, *, require_provider_config: bool | None = None) -> None:
        self.registry.snapshot()
        routes = [
            self.settings.narration_route,
            self.settings.remotion_route,
            self.settings.general_route,
        ]
        for route in routes:
            if not route.provider or not route.model:
                raise ModelGatewayError("model_route_missing", f"missing route for {route.task_family}")
            self._validate_route_contract(route)
            if (
                self.settings.require_model_config
                if require_provider_config is None
                else require_provider_config
            ):
                self._validate_provider_config(route)

        narration = self.settings.narration_route
        remotion = self.settings.remotion_route
        if (
            narration.endpoint != remotion.endpoint
            or narration.api_key_env != remotion.api_key_env
            or narration.request_model != remotion.request_model
        ):
            raise ModelGatewayError(
                "model_route_invalid",
                "narration and Remotion must share the pinned Azure Anthropic deployment",
            )

    def _validate_route_contract(self, route: ModelRoute) -> None:
        provider = route.provider.lower()
        if route.task_family in {"narration", "remotion"}:
            if provider != "azure_anthropic" or route.model != "case-video-claude":
                raise ModelGatewayError(
                    "model_route_invalid",
                    f"{route.task_family} must use Azure Anthropic case-video-claude",
                )
            if route.endpoint:
                parsed = urlparse(route.endpoint)
                path = parsed.path.rstrip("/").lower()
                if (
                    parsed.scheme != "https"
                    or not parsed.netloc
                    or not parsed.hostname
                    or not parsed.hostname.endswith(".services.ai.azure.com")
                    or not path.endswith("/v1/messages")
                    or "/openai/" in path
                    or "/deployments/" in path
                ):
                    raise ModelGatewayError(
                        "model_route_invalid",
                        f"{route.task_family} must use an Azure Anthropic Messages endpoint",
                    )
            if route.request_model != "case-video-claude":
                raise ModelGatewayError(
                    "model_route_invalid",
                    f"{route.task_family} must request the Azure Anthropic deployment case-video-claude",
                )
            return

        if route.task_family == "general":
            if provider != "openai" or route.model != "gpt-5.5" or route.request_model != "gpt-5.5":
                raise ModelGatewayError(
                    "model_route_invalid",
                    "general model tasks must use OpenAI Responses API with gpt-5.5",
                )
            if route.base_url:
                parsed = urlparse(route.base_url)
                path = parsed.path.rstrip("/").lower()
                if (
                    parsed.scheme not in {"http", "https"}
                    or not parsed.netloc
                    or path.endswith("/responses")
                    or "/openai/deployments/" in path
                ):
                    raise ModelGatewayError(
                        "model_route_invalid",
                        "general model tasks require an OpenAI Responses-compatible base URL",
                    )
            if (route.auth_mode or "bearer").lower() not in {"bearer", "api-key"}:
                raise ModelGatewayError(
                    "model_route_invalid",
                    "general model tasks require bearer or api-key authentication",
                )
            return

        raise ModelGatewayError(
            "model_route_invalid",
            f"unknown model task family: {route.task_family}",
        )

    def _validate_provider_config(self, route: ModelRoute) -> None:
        provider = route.provider.lower()
        if provider == "azure_anthropic":
            if not route.endpoint:
                raise ModelGatewayError(
                    "model_route_unavailable",
                    f"Azure Anthropic endpoint missing for {route.task_family}",
                )
            if not route.api_key_env or not os.getenv(route.api_key_env):
                raise ModelGatewayError(
                    "model_route_unavailable",
                    f"Azure Anthropic API key missing for {route.task_family}",
                )
            if not route.request_model:
                raise ModelGatewayError(
                    "model_route_unavailable",
                    f"Azure Anthropic deployment missing for {route.task_family}",
                )
        elif provider in {"openai", "openai_compatible"}:
            if not route.base_url:
                raise ModelGatewayError("model_route_unavailable", f"base URL missing for {route.task_family}")
            if not route.api_key_env or not os.getenv(route.api_key_env):
                raise ModelGatewayError("model_route_unavailable", f"API key missing for {route.task_family}")
        else:
            raise ModelGatewayError("model_provider_unsupported", f"unsupported provider: {route.provider}")

    def run_json(
        self,
        task: str,
        prompt_version: str,
        input_payload: dict[str, Any],
        job_id: str | None = None,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        try:
            spec = self.registry.spec(task)
            route = self.route_for_task(task)
            if prompt_version != spec.prompt_version:
                raise ModelGatewayError(
                    "contract_invalid",
                    f"task {task} is pinned to prompt {spec.prompt_version}, got {prompt_version}",
                )
            self.registry.validate_input(task, input_payload)
        except AppError as exc:
            if isinstance(exc, ModelGatewayError):
                raise
            raise ModelGatewayError(
                exc.code,
                exc.message,
                retryable=exc.retryable,
                status_code=exc.status_code,
                diagnostics=exc.diagnostics,
            ) from exc

        prompt_sha256 = self.registry.prompt_sha256(spec)
        input_schema = self.registry.contracts.ref(*spec.input_contract)
        output_schema = self.registry.contracts.ref(*spec.output_contract)
        input_hash = sha256_text(canonical_json(input_payload))
        route_snapshot = route.cache_fingerprint()
        idempotency_key = sha256_text(
            canonical_json(
                {
                    "job_id": job_id or "unscoped",
                    "task": task,
                    "input_hash": input_hash,
                    "prompt_sha256": prompt_sha256,
                    "input_schema_sha256": input_schema.sha256,
                    "output_schema_sha256": output_schema.sha256,
                    "route": route_snapshot,
                }
            )
        )
        effective_timeout = timeout_seconds or spec.timeout_seconds
        started = time.monotonic()
        run_id = f"modelrun_{uuid.uuid4().hex}"
        record: dict[str, Any] = {
            "run_id": run_id,
            "timestamp": utc_now_iso(),
            "task": task,
            "prompt_version": prompt_version,
            "prompt_sha256": prompt_sha256,
            "input_schema": input_schema.public_dict(),
            "output_schema": output_schema.public_dict(),
            "provider": route.provider,
            "model": route.model,
            "deployment": route.model if route.provider.lower() == "azure_anthropic" else None,
            "transport": route.public_dict()["transport"],
            "route_family": spec.route_family,
            "input_hash": input_hash,
            "idempotency_key": idempotency_key,
            "attempt": 1,
            "status": "started",
        }
        cache_context = (
            self.storage.model_cache_guard(job_id, idempotency_key)
            if job_id and self.storage
            else nullcontext()
        )
        with cache_context:
            if job_id and self.storage:
                cached = self.storage.read_model_cache(job_id, idempotency_key)
                if cached is not None:
                    output = cached.get("output")
                    if not isinstance(output, dict):
                        raise ModelGatewayError("model_output_invalid", "cached model output must be an object")
                    self.registry.validate_output(task, output)
                    reused = {
                        **record,
                        "timestamp": utc_now_iso(),
                        "status": "reused",
                        "duration_ms": int((time.monotonic() - started) * 1000),
                        "output_hash": sha256_text(canonical_json(output)),
                        "source_run_id": cached.get("run_id"),
                        "provider_call_id": cached.get("provider_call_id"),
                        "usage": {},
                        "normalizations": cached.get("normalizations", []),
                    }
                    self.storage.append_model_run(job_id, reused)
                    return output

            if job_id and self.storage:
                self.storage.append_model_run(job_id, record)

            try:
                if self.settings.dry_run:
                    output = self._dry_run_output(task, input_payload)
                    provider_call_id = None
                    usage: dict[str, Any] = {}
                    attempts = 1
                    normalizations: list[str] = []
                else:
                    self._validate_provider_config(route)
                    result = self._call_with_structure_repair(
                        task=task,
                        spec=spec,
                        route=route,
                        input_payload=input_payload,
                        timeout_seconds=effective_timeout,
                    )
                    output = result.payload
                    provider_call_id = result.provider_call_id
                    usage = result.usage
                    attempts = result.attempts
                    normalizations = list(result.normalizations)

                encoded = canonical_json(output).encode("utf-8")
                if len(encoded) > spec.max_output_bytes:
                    raise ModelGatewayError(
                        "model_output_invalid",
                        f"model output exceeds {spec.max_output_bytes} bytes",
                        retryable=True,
                    )
                self.registry.validate_output(task, output)
                output_hash = sha256_text(canonical_json(output))
                finished = {
                    **record,
                    "timestamp": utc_now_iso(),
                    "status": "succeeded",
                    "duration_ms": int((time.monotonic() - started) * 1000),
                    "attempts": attempts,
                    "output_hash": output_hash,
                    "provider_call_id": provider_call_id,
                    "usage": usage,
                    "normalizations": normalizations,
                }
                if job_id and self.storage:
                    self.storage.write_model_cache(
                        job_id,
                        idempotency_key,
                        {
                            "run_id": run_id,
                            "task": task,
                            "idempotency_key": idempotency_key,
                            "output_hash": output_hash,
                            "provider_call_id": provider_call_id,
                            "normalizations": normalizations,
                            "created_at": utc_now_iso(),
                            "output": output,
                        },
                    )
                    self.storage.append_model_run(job_id, finished)
                return output
            except AppError as exc:
                error = exc if isinstance(exc, ModelGatewayError) else ModelGatewayError(
                    exc.code,
                    exc.message,
                    retryable=exc.retryable,
                    status_code=exc.status_code,
                    diagnostics=exc.diagnostics,
                )
                failed = {
                    **record,
                    "timestamp": utc_now_iso(),
                    "status": "failed",
                    "duration_ms": int((time.monotonic() - started) * 1000),
                    "error_code": error.code,
                    "message": error.message,
                }
                if job_id and self.storage:
                    self.storage.append_model_run(job_id, failed)
                raise error

    def _call_with_structure_repair(
        self,
        task: str,
        spec: TaskSpec,
        route: ModelRoute,
        input_payload: dict[str, Any],
        timeout_seconds: int,
    ) -> ProviderResult:
        system_prompt = self.registry.prompt(task)
        repair_note: str | None = None
        last_error: AppError | None = None
        for attempt in range(spec.max_structure_repairs + 1):
            provider_result = self._call_provider(
                route,
                input_payload,
                timeout_seconds,
                system_prompt=system_prompt,
                repair_note=repair_note,
            )
            normalized_payload, normalizations = self._normalize_contract_literals(
                spec,
                provider_result.payload,
            )
            result = ProviderResult(
                payload=normalized_payload,
                provider_call_id=provider_result.provider_call_id,
                usage=provider_result.usage,
                normalizations=normalizations,
            )
            encoded = canonical_json(result.payload).encode("utf-8")
            if len(encoded) > spec.max_output_bytes:
                last_error = AppError("model_output_invalid", f"model output exceeds {spec.max_output_bytes} bytes")
            else:
                try:
                    self.registry.validate_output(task, result.payload)
                    return ProviderResult(
                        payload=result.payload,
                        provider_call_id=result.provider_call_id,
                        usage=result.usage,
                        attempts=attempt + 1,
                        normalizations=result.normalizations,
                    )
                except AppError as exc:
                    last_error = exc
            if attempt < spec.max_structure_repairs:
                repair_note = (
                    "The previous JSON failed contract validation. Return a complete replacement JSON object "
                    f"that satisfies the same output contract. Validation error: {last_error.message}"
                )
        assert last_error is not None
        raise ModelGatewayError(
            "model_output_invalid",
            last_error.message,
            retryable=True,
            diagnostics={"task": task, "attempts": spec.max_structure_repairs + 1},
        )

    def _normalize_contract_literals(
        self,
        spec: TaskSpec,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], tuple[str, ...]]:
        """Normalize only unambiguous JSON scalar encodings declared by the contract."""
        schema = self.registry.contracts.schema(*spec.output_contract)
        version_schema = schema.get("properties", {}).get("version", {})
        expected_version = version_schema.get("const")
        actual_version = payload.get("version")
        if (
            isinstance(expected_version, str)
            and isinstance(actual_version, int)
            and not isinstance(actual_version, bool)
            and str(actual_version) == expected_version
        ):
            normalized = dict(payload)
            normalized["version"] = expected_version
            return normalized, ("version:int-to-string",)
        return payload, ()

    def _call_provider(
        self,
        route: ModelRoute,
        input_payload: dict[str, Any],
        timeout_seconds: int,
        *,
        system_prompt: str,
        repair_note: str | None = None,
    ) -> ProviderResult:
        provider = route.provider.lower()
        media = input_payload.get("media", [])
        text_input = {key: value for key, value in input_payload.items() if key != "media"}
        if media:
            text_input["media"] = [
                {
                    "media_id": item["media_id"],
                    "mime_type": item["mime_type"],
                    "description": item.get("description", ""),
                }
                for item in media
            ]
        user_content: dict[str, Any] = {"input": text_input}
        if repair_note:
            user_content["repair_instruction"] = repair_note
        output_contract = self.registry.spec(str(input_payload["task"])).output_contract
        output_schema = self.registry.contracts.schema(*output_contract)
        if provider == "azure_anthropic":
            assert route.endpoint is not None
            endpoint = route.endpoint.rstrip("/")
            url = endpoint if endpoint.endswith("/v1/messages") else f"{endpoint}/v1/messages"
            headers = {
                "x-api-key": os.environ[route.api_key_env or "AZURE_ANTHROPIC_API_KEY"],
                "anthropic-version": route.api_version or "2023-06-01",
                "content-type": "application/json",
            }
            anthropic_content: str | list[dict[str, Any]] = json.dumps(user_content, ensure_ascii=False)
            if media:
                anthropic_content = [
                    {"type": "text", "text": json.dumps(user_content, ensure_ascii=False)},
                    *[
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": item["mime_type"],
                                "data": item["data_base64"],
                            },
                        }
                        for item in media
                    ],
                ]
            request_payload = {
                "model": route.request_model or route.model,
                "max_tokens": 16_384,
                "system": system_prompt,
                "messages": [
                    {"role": "user", "content": anthropic_content}
                ],
                "tools": [
                    {
                        "name": "emit_contract_output",
                        "description": "Return the complete final result that conforms to the supplied JSON Schema.",
                        "input_schema": output_schema,
                    }
                ],
                "tool_choice": {"type": "tool", "name": "emit_contract_output"},
            }
        elif provider in {"openai", "openai_compatible"}:
            assert route.base_url is not None
            url = f"{route.base_url.rstrip('/')}/responses"
            api_key = os.environ[route.api_key_env or "CASE_VIDEO_GENERAL_API_KEY"]
            auth_mode = (route.auth_mode or "bearer").lower()
            headers = (
                {"api-key": api_key}
                if auth_mode == "api-key"
                else {"Authorization": f"Bearer {api_key}"}
            )
            responses_input: str | list[dict[str, Any]] = json.dumps(user_content, ensure_ascii=False)
            if media:
                responses_input = [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": json.dumps(user_content, ensure_ascii=False)},
                            *[
                                {
                                    "type": "input_image",
                                    "image_url": f"data:{item['mime_type']};base64,{item['data_base64']}",
                                    "detail": "high",
                                }
                                for item in media
                            ],
                        ],
                    }
                ]
            request_payload = {
                "model": route.request_model or route.model,
                "instructions": system_prompt,
                "input": responses_input,
                "store": False,
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": output_contract[0].replace(".", "_"),
                        "schema": output_schema,
                        "strict": False,
                    }
                },
            }
        else:
            raise ModelGatewayError("model_provider_unsupported", f"unsupported provider: {route.provider}")

        try:
            response = httpx.post(
                url,
                headers=headers,
                json=request_payload,
                timeout=timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise ModelGatewayError("model_provider_error", "model provider request failed") from exc
        if response.status_code >= 400:
            raise ModelGatewayError("model_provider_error", f"provider returned HTTP {response.status_code}")
        try:
            payload = response.json()
            if not isinstance(payload, dict):
                raise ModelGatewayError("model_output_invalid", "provider response must be a JSON object")
            if provider == "azure_anthropic":
                parsed = self._anthropic_tool_output(payload)
            else:
                content = self._responses_output_text(payload)
                parsed = json.loads(content)
            if not isinstance(parsed, dict):
                raise ModelGatewayError("model_output_invalid", "provider JSON content must be an object")
            return ProviderResult(
                payload=parsed,
                provider_call_id=payload.get("id"),
                usage=payload.get("usage") if isinstance(payload.get("usage"), dict) else {},
            )
        except (KeyError, IndexError, json.JSONDecodeError, ValueError) as exc:
            raise ModelGatewayError("model_output_invalid", "provider did not return valid JSON content") from exc

    @staticmethod
    def _anthropic_tool_output(payload: dict[str, Any]) -> dict[str, Any]:
        text_candidates: list[str] = []
        for content in payload.get("content", []):
            if not isinstance(content, dict):
                continue
            if content.get("type") == "tool_use" and content.get("name") == "emit_contract_output":
                tool_input = content.get("input")
                if isinstance(tool_input, dict):
                    return tool_input
            if content.get("type") == "text" and isinstance(content.get("text"), str):
                text_candidates.append(content["text"])
        for text_value in text_candidates:
            try:
                parsed = json.loads(text_value)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        raise ModelGatewayError("model_output_invalid", "Anthropic Messages API did not return tool JSON")

    @staticmethod
    def _responses_output_text(payload: dict[str, Any]) -> str:
        direct = payload.get("output_text")
        if isinstance(direct, str) and direct:
            return direct
        for item in payload.get("output", []):
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if not isinstance(content, dict):
                    continue
                if content.get("type") == "refusal":
                    raise ModelGatewayError("model_output_invalid", "model refused the structured request")
                if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                    return content["text"]
        raise ModelGatewayError("model_output_invalid", "Responses API did not return output text")

    @staticmethod
    def _source_refs(input_payload: dict[str, Any]) -> list[str]:
        refs = [
            str(item.get("source_id"))
            for item in input_payload.get("source_excerpts", [])
            if isinstance(item, dict) and item.get("source_id")
        ]
        context_refs = input_payload.get("context", {}).get("source_refs", [])
        if isinstance(context_refs, list):
            refs.extend(str(item) for item in context_refs if item)
        return list(dict.fromkeys(refs)) or ["source:dry-run"]

    def _dry_run_output(self, task: str, input_payload: dict[str, Any]) -> dict[str, Any]:
        context = input_payload.get("context", {})
        source_refs = self._source_refs(input_payload)
        title = str(context.get("title") or context.get("project_name") or "从混乱到共识：一次销售管理转型")
        title = title.replace("\r", " ").replace("\n", " ").strip()[:120] or "销售管理案例"
        opener = "这里是销售不复杂，用销售和管理经典案例帮您揭开销售的秘密。"
        closer = "这期的《销售不复杂》就到这里。帮你揭开销售的魔法秘密，让销售不再复杂。我们下期再见。"

        if task == "source.classify":
            return {
                "material_types": ["case_source"],
                "usability": "sufficient",
                "gaps": [],
                "summary": "dry-run：来源已完成合同级分类。",
            }
        if task == "case.extract":
            return {
                "facts": [
                    {
                        "fact_id": "fact-001",
                        "claim": "dry-run：来源材料可用于构建案例。",
                        "confidence": 1.0,
                        "source_refs": source_refs,
                        "notes": "仅用于服务器流水线验收。",
                    }
                ],
                "conflicts": [],
            }
        if task == "case.model":
            return {
                "version": "1",
                "actors": [{"name": "销售团队", "role": "案例主体"}],
                "situation": "团队需要在有限信息下形成清晰的客户行动方案。",
                "conflict": "目标、责任与执行节奏尚未统一。",
                "turning_points": ["团队核对事实并明确关键责任。"],
                "outcome": "团队形成了可执行且可复核的方案。",
                "lessons": ["先建立事实共识，再推进销售行动。"],
                "numbers": [],
                "source_refs": source_refs,
                "uncertainties": [],
            }
        if task in {"narration.compose", "narration.rewrite"}:
            duration = context.get("target_duration_seconds")
            if not isinstance(duration, dict):
                duration = {"min": 240, "max": 420}
            minimum = duration.get("min", 240)
            maximum = duration.get("max", 420)
            if not isinstance(minimum, int) or not isinstance(maximum, int) or minimum < 1 or maximum < minimum:
                minimum, maximum = 240, 420
            target_chars = round(((minimum + maximum) / 2) * 4)
            body_sentences = [
                "故事发生在一家正在调整销售管理方式的企业。客户需求持续变化，销售、交付和管理团队掌握的信息却分散在不同会议和个人记录里。",
                "表面上看，大家都在努力推进项目，真正影响结果的事实、责任和决策条件却没有形成共同版本。每次沟通都会重新解释背景，行动节奏因此越来越慢。",
                "销售负责人先暂停了零散追问，把客户目标、关键角色、已有承诺和未确认事项逐条放到同一张事实清单中。团队只记录能够追溯来源的内容，也明确标注仍需验证的判断。",
                "这次整理让矛盾迅速显现。客户关注的是业务结果，内部讨论长期停留在产品功能；客户希望看到实施路径，团队提供的材料却缺少责任人和完成条件。",
                "负责人随后组织跨部门复盘，让销售说明客户场景，让交付评估资源边界，让管理者确认授权范围。每个人都围绕同一组事实回答问题，讨论开始从观点争执转向行动选择。",
                "团队把客户目标拆成可观察的业务变化，再把方案能力映射到这些变化。无法证明的承诺被删除，需要补充的数据被列入验证任务，CRM中的机会记录也同步更新。",
                "新的方案没有堆叠更多口号。它清楚写出客户为什么现在行动、哪些角色会受到影响、实施过程中可能遇到什么阻力，以及双方分别需要完成哪些准备。",
                "当责任边界被说明后，内部协作明显顺畅。销售知道何时邀请专家，交付知道哪些条件必须提前确认，管理者也能依据风险和价值决定资源投入。",
                "客户在下一轮沟通中看到了变化。团队能够直接回应业务目标，也能坦诚说明限制和依赖。清晰的边界提升了可信度，双方开始共同讨论落地顺序和验收方式。",
                "项目推进过程中，负责人持续用事实清单核对新信息。任何范围变化都会关联到负责人、时间点和影响，重要决定也会留下来源和理由，避免口头共识在会后消失。",
                "这种做法还改变了销售预测。机会阶段不再依赖乐观判断，而是依据客户行动、内部资源和关键风险更新。管理层看到的是可解释的进度，也能更早处理真正的阻塞。",
                "最终，团队形成了一套稳定的协作节奏。客户获得了可执行的路径，内部减少了反复沟通，销售也能够把每一次承诺落实到具体行动和验证标准。",
                "这个案例说明，销售管理首先要建立共同事实。事实清楚以后，责任才能落位；责任明确以后，行动才能形成节奏；行动持续被验证，信任和结果才会逐步积累。",
                "面对复杂机会时，可以先问三个问题：客户真正要改变什么，当前判断依据来自哪里，下一步由谁在什么条件下完成。把答案写清楚，团队就获得了共同导航。",
                "好的销售方案既要有吸引力，也要经得住复核。它连接客户目标、组织角色、资源约束和实施动作，让每一方都能判断价值、风险与自己的责任。",
                "管理者的任务是维护这条连接。他需要及时纠正未经验证的推断，保护跨部门协作的节奏，并让团队在信息变化时仍然使用同一套决策依据。",
                "当事实、责任和行动被持续连接，销售过程会变得透明。团队可以更快发现偏差，更早调整资源，也能用可靠证据向客户解释为什么这个方案值得推进。",
            ]
            body: list[str] = []
            sentence_index = 0
            fixed_chars = len(re.sub(r"\s+", "", opener + closer))
            while fixed_chars + len(re.sub(r"\s+", "", "".join(body))) < target_chars:
                body.append(body_sentences[sentence_index % len(body_sentences)])
                sentence_index += 1
            narration = f"{opener}\n\n" + "\n\n".join(body) + f"\n\n{closer}"
            return {
                "version": "1",
                "title": title,
                "narration": narration,
                "change_summary": "dry-run：生成满足合同与栏目规范的标题和旁白。",
                "addressed_issue_ids": [
                    str(item.get("issue_id"))
                    for item in input_payload.get("issues", [])
                    if isinstance(item, dict) and item.get("issue_id")
                ],
            }
        if task == "editorial.review":
            return {
                "version": "1",
                "verdict": "pass",
                "issues": [],
                "summary": "dry-run：标题与旁白通过合同级审阅。",
            }
        if task in {"remotion.plan", "remotion.repair"}:
            unit_count = context.get("unit_count", 1)
            if not isinstance(unit_count, int) or unit_count < 1:
                unit_count = 1
            return {
                "version": "2",
                "projectType": "sales-management",
                "visualStyle": "warm manager silhouettes with disciplined navy, cobalt and burnt-orange contrast",
                "cover": {
                    "title": title,
                    "subtitle": "从事实、责任到行动",
                    "kicker": "案例开场",
                    "throughUnit": 1,
                    "proof": "基于来源材料与旁白单元",
                },
                "brand": "销售不复杂",
                "subtitleLabel": "销售不复杂",
                "direction": {
                    "visualThesis": "以单一管理者剪影和逐步出现的事实链建立叙事重心。",
                    "pacingArc": "先稳定建立人物与问题，再用证据推进，结尾留出反思空间。",
                    "densityStrategy": "每个时刻只保留一个主要信息层，字幕区之外维持清晰负空间。",
                    "continuityRules": ["主角方向与暖色背光保持一致。"],
                    "avoid": ["固定三段式构图", "按序号轮换转场"],
                },
                "chrome": {
                    "brandBug": True,
                    "chapterBadge": True,
                    "subtitleBar": True,
                    "progressRail": False,
                    "cover": True,
                },
                "assets": [
                    {
                        "id": "scene-001-bg",
                        "sceneId": "scene-001",
                        "role": "context",
                        "promptIntent": "一位管理者面对由事实节点构成的决策路径，留出清晰字幕和标题负空间。",
                        "continuity": "深蓝轮廓、暖橙背光、无可读文字。",
                    }
                ],
                "scenes": [
                    {
                        "id": "scene-001",
                        "units": [1, unit_count],
                        "chapter": "01",
                        "kicker": "案例开场",
                        "layout": "director-canvas",
                        "visualMode": "editorial",
                        "dramaticFunction": "建立案例世界、主角与即将被解决的管理冲突。",
                        "directorialIntent": "用一个稳定的主体建立案例世界，再让事实链成为唯一的视觉推进线索。",
                        "keywords": [],
                        "backgrounds": [],
                        "sceneMotion": {
                            "enter": "fade",
                            "exit": "fade",
                            "enterFrames": 12,
                            "exitFrames": 10,
                        },
                        "transition": "none",
                        "transitionFrames": 18,
                        "visualBeats": [
                            {
                                "id": "scene-001-beat-01",
                                "atUnit": 1,
                                "visualIntent": "context",
                                "purpose": "establish",
                                "directorialIntent": "让主体先被看见，画面保持安静，不用装饰性信息抢夺注意力。",
                                "composition": "full-bleed",
                                "baseAsset": "scene-001-bg",
                                "baseFit": "cover",
                                "transition": "cut",
                                "render": {
                                    "cameraPath": {
                                        "startScale": 1.02,
                                        "endScale": 1.06,
                                        "startX": 0,
                                        "endX": 8,
                                        "startY": 0,
                                        "endY": -4,
                                    },
                                    "treatmentColor": "#00000000",
                                    "ambientOpacity": 0,
                                    "vignette": 0.08,
                                    "overlay": "read-left",
                                    "transitionFrames": 10,
                                    "layerEnterFrames": 8,
                                    "layerExitFrames": 7,
                                    "layerStaggerFrames": 0,
                                    "emphasisScale": 1,
                                    "pulse": False,
                                    "flashbackFrame": False,
                                    "canvasTone": "transparent",
                                },
                                "layers": [],
                            }
                        ],
                    }
                ],
            }
        if task == "remotion.frame-review":
            frame_records = context.get("frames", [])
            if not isinstance(frame_records, list) or not frame_records:
                frame_records = [{"frame_id": "frame-001", "scene_id": "scene-001"}]
            scene_ids = list(
                dict.fromkeys(str(item.get("scene_id") or "scene-001") for item in frame_records)
            )
            return {
                "version": "1",
                "verdict": "pass",
                "summary": "dry-run：代表帧与导演意图一致。",
                "scene_reviews": [
                    {
                        "scene_id": scene_id,
                        "frame_ids": [
                            str(item.get("frame_id") or "frame-001")
                            for item in frame_records
                            if str(item.get("scene_id") or "scene-001") == scene_id
                        ],
                        "intent_alignment": 5,
                        "hierarchy": 5,
                        "legibility": 5,
                        "density": 5,
                        "assessment": "dry-run：画面结构清晰。",
                    }
                    for scene_id in scene_ids
                ],
                "issues": [],
            }
        if task == "image_prompt.refine":
            asset_ids = context.get("asset_ids", ["scene-001-bg"])
            if not isinstance(asset_ids, list):
                asset_ids = ["scene-001-bg"]
            return {
                "version": "2",
                "prompts": [
                    {
                        "asset_id": str(asset_id),
                        "prompt": "Warm sales-management silhouette, deep navy layers, cobalt blue and burnt orange backlight, cream negative space, cut-paper screen-print texture, no text.",
                        "negative_prompt": "logos, letters, numerals, watermark, UI screenshot, detailed faces",
                        "style_family": "sales-management-silhouette",
                    }
                    for asset_id in asset_ids
                ],
            }
        if task == "delivery.summarize":
            return {
                "version": "1",
                "status": "ready",
                "summary": "dry-run：交付物已完成服务器合同级检查。",
                "qa_highlights": ["结构化合同通过", "模型路由已固定"],
                "remaining_risks": [],
            }
        raise ModelGatewayError("model_task_unregistered", f"model task is not registered: {task}")
