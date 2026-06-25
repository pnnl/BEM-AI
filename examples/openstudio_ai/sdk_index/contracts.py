from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SdkLookupRequest:
    class_name: str
    method_name: str | None = None


@dataclass(frozen=True)
class SdkLookupResult:
    class_name: str
    method_name: str | None
    summary: str
    source: str

