from __future__ import annotations

from typing import Any

from examples.openstudio_ai.openstudio_mcp_server.sdk_docs import (
    SdkDocsUnavailableError,
)
from examples.openstudio_ai.openstudio_mcp_server.tools.schemas import (
    error_payload,
    success_payload,
)


def register_sdk_doc_tools(mcp, service) -> None:
    @mcp.tool(
        name="sdk_docs_route",
        description=(
            "Route an OpenStudio SDK scripting request to likely wiki packs "
            "and SDK classes."
        ),
    )
    async def sdk_docs_route(query: str, limit: int = 6) -> dict[str, Any]:
        try:
            return success_payload(**service.sdk_docs_route(query=query, limit=limit))
        except SdkDocsUnavailableError as exc:
            return error_payload("not_configured", str(exc), retryable=False)
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)

    @mcp.tool(
        name="sdk_docs_find_classes",
        description="Find OpenStudio model SDK classes by name or keyword in local SDK HTML docs.",
    )
    async def sdk_docs_find_classes(
        query: str,
        include_detail: bool = False,
        limit: int = 20,
    ) -> dict[str, Any]:
        try:
            return success_payload(
                classes=service.sdk_docs_find_classes(
                    query=query,
                    include_detail=include_detail,
                    limit=limit,
                )
            )
        except SdkDocsUnavailableError as exc:
            return error_payload("not_configured", str(exc), retryable=False)
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)

    @mcp.tool(
        name="sdk_docs_list_methods",
        description="List documented methods for one OpenStudio model SDK class.",
    )
    async def sdk_docs_list_methods(
        class_name: str,
        keyword: str | None = None,
        limit: int = 80,
    ) -> dict[str, Any]:
        try:
            return success_payload(
                **service.sdk_docs_list_methods(
                    class_name=class_name,
                    keyword=keyword,
                    limit=limit,
                )
            )
        except SdkDocsUnavailableError as exc:
            return error_payload("not_configured", str(exc), retryable=False)
        except KeyError as exc:
            return error_payload("not_found", str(exc), retryable=False)
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)

    @mcp.tool(
        name="sdk_docs_get_method",
        description=(
            "Get exact signature and documentation for an OpenStudio model "
            "SDK class method."
        ),
    )
    async def sdk_docs_get_method(
        class_name: str,
        method_name: str,
        anchor: str | None = None,
        signature_contains: str | None = None,
    ) -> dict[str, Any]:
        try:
            return success_payload(
                **service.sdk_docs_get_method(
                    class_name=class_name,
                    method_name=method_name,
                    anchor=anchor,
                    signature_contains=signature_contains,
                )
            )
        except SdkDocsUnavailableError as exc:
            return error_payload("not_configured", str(exc), retryable=False)
        except KeyError as exc:
            return error_payload("not_found", str(exc), retryable=False)
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)

    @mcp.tool(
        name="sdk_docs_search_methods",
        description="Search documented OpenStudio model SDK method names across classes.",
    )
    async def sdk_docs_search_methods(
        keyword: str,
        class_filter: str | None = None,
        include_detail: bool = False,
        limit: int = 40,
    ) -> dict[str, Any]:
        try:
            return success_payload(
                methods=service.sdk_docs_search_methods(
                    keyword=keyword,
                    class_filter=class_filter,
                    include_detail=include_detail,
                    limit=limit,
                )
            )
        except SdkDocsUnavailableError as exc:
            return error_payload("not_configured", str(exc), retryable=False)
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)
