"""Project-aware, secret-safe credential scheduling for Gemini API calls.

This module does not make network calls. Secrets are held only in private,
non-serializable runtime objects; public metadata uses slot ids and labels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import re
import time
from typing import Callable, Mapping, Optional


POOL_VERSION = "GEMINI_KEY_POOL_V1"
UNKNOWN_PROJECT_LABEL = "PROJECT_GROUP_UNKNOWN"
_KEY_PATTERN = re.compile(r"^GEMINI_API_KEY_(\d+)$")


class GeminiConfigError(RuntimeError):
    """A deliberately sanitized configuration failure."""


class GeminiPoolExhausted(RuntimeError):
    """No credential slot is currently eligible."""


@dataclass(frozen=True)
class CredentialConfig:
    slot_id: str
    env_name: str
    project_label: str
    group_id: str
    _api_key: str = field(repr=False, compare=False)

    def public_metadata(self) -> dict[str, str]:
        return {
            "slot_id": self.slot_id,
            "env_name": self.env_name,
            "project_label": self.project_label,
        }


@dataclass(frozen=True)
class GeminiRuntimeConfig:
    credentials: tuple[CredentialConfig, ...]
    model: str

    @property
    def project_group_count(self) -> int:
        return len({slot.group_id for slot in self.credentials})

    def public_summary(self) -> dict[str, object]:
        return {
            "credential_slots": len(self.credentials),
            "project_groups": self.project_group_count,
            "model_configured": bool(self.model),
        }


@dataclass(frozen=True)
class CredentialLease:
    slot_id: str
    project_label: str
    group_id: str
    _api_key: str = field(repr=False, compare=False)

    @property
    def api_key(self) -> str:
        return self._api_key

    def public_metadata(self) -> dict[str, str]:
        return {"slot_id": self.slot_id, "project_label": self.project_label}


@dataclass
class _SlotState:
    config: CredentialConfig
    enabled: bool = True


@dataclass
class _GroupState:
    group_id: str
    slots: list[_SlotState]
    cursor: int = 0
    cooldown_until: float = 0.0


def _parse_dotenv(path: Path) -> dict[str, str]:
    """Parse the deliberately small KEY=VALUE subset needed by this runtime."""
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise GeminiConfigError(f"Invalid .env syntax at line {line_number}")
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'\"', "'"}:
            value = value[1:-1]
        values[name] = value
    return values


def load_runtime_config(
    dotenv_path: Path | str = Path(".env"),
    environ: Optional[Mapping[str, str]] = None,
) -> GeminiRuntimeConfig:
    """Load only Gemini configuration, with process environment taking priority."""
    source = _parse_dotenv(Path(dotenv_path))
    process_env = os.environ if environ is None else environ
    for name, value in process_env.items():
        if name == "GEMINI_MODEL" or _KEY_PATTERN.match(name) or name.startswith("GEMINI_PROJECT_LABEL_"):
            source[name] = value

    numbered_keys: list[tuple[int, str, str]] = []
    for name, value in source.items():
        match = _KEY_PATTERN.match(name)
        if match and value.strip():
            numbered_keys.append((int(match.group(1)), name, value.strip()))
    numbered_keys.sort(key=lambda item: item[0])

    credentials: list[CredentialConfig] = []
    seen_secrets: set[str] = set()
    seen_numbers: set[int] = set()
    configured_secrets = [secret for _, _, secret in numbered_keys]
    for number, env_name, secret in numbered_keys:
        if number < 1 or number in seen_numbers:
            raise GeminiConfigError("Duplicate or invalid Gemini credential slot number")
        seen_numbers.add(number)
        if secret in seen_secrets:
            raise GeminiConfigError("Duplicate Gemini credential configuration")
        seen_secrets.add(secret)
        slot_id = f"gemini_slot_{number}"
        supplied_label = source.get(f"GEMINI_PROJECT_LABEL_{number}", "").strip()
        if supplied_label and any(value in supplied_label for value in configured_secrets):
            raise GeminiConfigError("Gemini project label contains credential material")
        project_label = supplied_label or UNKNOWN_PROJECT_LABEL
        # Every unlabeled credential gets an independent unknown group. This does
        # not claim independent quota; the uncertainty is explicit in metadata.
        group_id = supplied_label if supplied_label else f"{UNKNOWN_PROJECT_LABEL}:{slot_id}"
        credentials.append(
            CredentialConfig(
                slot_id=slot_id,
                env_name=env_name,
                project_label=project_label,
                group_id=group_id,
                _api_key=secret,
            )
        )
    return GeminiRuntimeConfig(tuple(credentials), source.get("GEMINI_MODEL", "").strip())


class GeminiKeyPool:
    """Deterministic round robin across project groups and their slots."""

    def __init__(
        self,
        credentials: tuple[CredentialConfig, ...] | list[CredentialConfig],
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not credentials:
            raise GeminiConfigError("No Gemini credential slots configured")
        self._clock = clock
        grouped: dict[str, list[_SlotState]] = {}
        group_order: list[str] = []
        for credential in credentials:
            if credential.group_id not in grouped:
                grouped[credential.group_id] = []
                group_order.append(credential.group_id)
            grouped[credential.group_id].append(_SlotState(credential))
        self._groups = [_GroupState(group_id, grouped[group_id]) for group_id in group_order]
        self._group_cursor = 0

    def acquire(self, now: Optional[float] = None) -> CredentialLease:
        current = self._clock() if now is None else now
        for offset in range(len(self._groups)):
            group_index = (self._group_cursor + offset) % len(self._groups)
            group = self._groups[group_index]
            if group.cooldown_until > current:
                continue
            for slot_offset in range(len(group.slots)):
                slot_index = (group.cursor + slot_offset) % len(group.slots)
                slot = group.slots[slot_index]
                if not slot.enabled:
                    continue
                group.cursor = (slot_index + 1) % len(group.slots)
                self._group_cursor = (group_index + 1) % len(self._groups)
                config = slot.config
                return CredentialLease(
                    config.slot_id,
                    config.project_label,
                    config.group_id,
                    config._api_key,
                )
        raise GeminiPoolExhausted("No eligible Gemini credential slot")

    def cool_project_group(self, slot_id: str, seconds: float, now: Optional[float] = None) -> None:
        current = self._clock() if now is None else now
        group = self._group_for_slot(slot_id)
        group.cooldown_until = max(group.cooldown_until, current + max(0.0, seconds))

    def disable_slot(self, slot_id: str) -> None:
        for group in self._groups:
            for slot in group.slots:
                if slot.config.slot_id == slot_id:
                    slot.enabled = False
                    return
        raise GeminiConfigError("Unknown Gemini credential slot")

    def has_available(self, now: Optional[float] = None) -> bool:
        current = self._clock() if now is None else now
        return any(
            group.cooldown_until <= current and any(slot.enabled for slot in group.slots)
            for group in self._groups
        )

    def seconds_until_available(self, now: Optional[float] = None) -> Optional[float]:
        current = self._clock() if now is None else now
        waits = [
            max(0.0, group.cooldown_until - current)
            for group in self._groups
            if any(slot.enabled for slot in group.slots)
        ]
        return min(waits) if waits else None

    def public_metadata(self) -> dict[str, object]:
        return {
            "pool": POOL_VERSION,
            "groups": [
                {
                    "project_label": group.slots[0].config.project_label,
                    "slots": [slot.config.public_metadata() for slot in group.slots],
                }
                for group in self._groups
            ],
        }

    def redact(self, value: str) -> str:
        redacted = value
        for group in self._groups:
            for slot in group.slots:
                redacted = redacted.replace(slot.config._api_key, "[REDACTED]")
        return redacted

    def _group_for_slot(self, slot_id: str) -> _GroupState:
        for group in self._groups:
            if any(slot.config.slot_id == slot_id for slot in group.slots):
                return group
        raise GeminiConfigError("Unknown Gemini credential slot")
