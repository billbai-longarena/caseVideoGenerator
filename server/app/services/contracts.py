from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from server.app.core.errors import AppError


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class ContractRef:
    name: str
    version: str
    path: Path
    sha256: str

    def public_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "version": self.version,
            "path": self.path.as_posix(),
            "sha256": self.sha256,
        }


class ContractRegistry:
    def __init__(self, schema_root: Path) -> None:
        self.schema_root = schema_root.resolve()
        self._schema_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._ref_cache: dict[tuple[str, str], ContractRef] = {}

    def ref(self, name: str, version: str) -> ContractRef:
        key = (name, version)
        if key in self._ref_cache:
            return self._ref_cache[key]
        path = (self.schema_root / name / f"{version}.json").resolve()
        if self.schema_root not in path.parents or not path.is_file():
            raise AppError("contract_invalid", f"contract not found: {name}/{version}")
        raw = path.read_bytes()
        try:
            schema = json.loads(raw.decode("utf-8"))
            Draft202012Validator.check_schema(schema)
        except (UnicodeDecodeError, json.JSONDecodeError, SchemaError) as exc:
            raise AppError("contract_invalid", f"invalid contract schema: {name}/{version}") from exc
        ref = ContractRef(name=name, version=version, path=path.relative_to(self.schema_root), sha256=sha256_bytes(raw))
        self._schema_cache[key] = schema
        self._ref_cache[key] = ref
        return ref

    def schema(self, name: str, version: str) -> dict[str, Any]:
        self.ref(name, version)
        return self._schema_cache[(name, version)]

    def validate(
        self,
        name: str,
        version: str,
        payload: Any,
        *,
        error_code: str = "contract_invalid",
    ) -> None:
        validator = Draft202012Validator(self.schema(name, version))
        errors = sorted(validator.iter_errors(payload), key=lambda item: list(item.absolute_path))
        if not errors:
            return
        error: ValidationError = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        raise AppError(
            error_code,
            f"{name}/{version} validation failed at {location}: {error.message}",
            diagnostics={"contract": name, "version": version, "path": location},
        )

    def snapshot(self, refs: set[tuple[str, str]]) -> dict[str, dict[str, str]]:
        return {
            name: self.ref(name, version).public_dict()
            for name, version in sorted(refs)
        }
