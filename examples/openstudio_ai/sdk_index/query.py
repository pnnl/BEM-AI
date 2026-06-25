from __future__ import annotations

from examples.openstudio_ai.sdk_index.contracts import SdkLookupRequest, SdkLookupResult


def query_sdk_index(request: SdkLookupRequest) -> SdkLookupResult:
    return SdkLookupResult(
        class_name=request.class_name,
        method_name=request.method_name,
        summary="SDK index query implementation pending.",
        source="sdk_index",
    )

