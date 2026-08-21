from __future__ import annotations

from enum import Enum


class JailbreakType(str, Enum):
    ROOTLESS = "rootless"
    ROOTHIDE = "roothide"


def normalize_jailbreak_type(value: str | JailbreakType) -> JailbreakType:
    try:
        return JailbreakType(value)
    except ValueError as exc:
        raise ValueError(f"不支持的越狱类型：{value}") from exc
