import logging
import math
from datetime import datetime, timezone
from string import Formatter
from typing import Any, Mapping, Optional, List, Sequence

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from automa_ai.memory.memory_stores import BaseMemoryStore
from automa_ai.memory.memory_types import MemoryEntry, MemoryType

logger = logging.getLogger(__name__)

_ROLE_TO_MESSAGE: dict[str, type[BaseMessage]] = {
    "human": HumanMessage,
    "agent": AIMessage,
    "tool": ToolMessage,
    "system": SystemMessage,
}

_SUPPORTED_PLACEHOLDERS = frozenset({"actor_id", "session_id", "task_id", "user_id"})


def _validate_identity_value(field: str, value: Any) -> str:
    """Validate that an identity value is a single, slash-free path segment.

    Prevents values like "alice/../bob" from reshaping the rendered namespace
    path.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"{field} must be a non-empty, non-blank string, got {value!r}."
        )
    if "/" in value:
        raise ValueError(
            f"{field}={value!r} contains '/', which would change the AgentCore "
            "namespace path. Identity values must be single path segments."
        )
    return value


# Rank assigned to a record the backend returned without a usable score, so it
# sorts between clearly-relevant and clearly-irrelevant hits.
_UNSCORED_RELEVANCE = 0.5


def _relevance_of(item: Any) -> Optional[float]:
    """Return the item's search score, or None if missing/non-finite.
    """
    score = getattr(item, "score", None)
    if score is None:
        return None
    try:
        score = float(score)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(score):
        return None
    return score


class AgentCoreMemoryStore(BaseMemoryStore):
    """Long-term memory storage backed by AWS Bedrock AgentCore Memory."""

    @classmethod
    def from_config(cls, config: dict) -> "BaseMemoryStore":
        # Expected keys:
        #   memory_id (str, required): AgentCore Memory resource ID
        #   namespaces (dict, required): MemoryType -> template or [templates]
        #       Templates may reference {actor_id}, {session_id}, {task_id},
        #       {user_id}. Must match the namespaces the AWS strategy extracts
        #       into. Example: {"long_term": "/preferences/{actor_id}"}
        #   region (str, optional)
        #   boto3_kwargs (dict, optional)
        memory_id = config.get("memory_id")
        if not memory_id:
            raise ValueError("memory_id must be defined for AgentCoreMemoryStore.")

        namespaces = config.get("namespaces")
        if not namespaces:
            raise ValueError(
                "namespaces must be defined for AgentCoreMemoryStore. AgentCore "
                "retrieves extracted memories from the strategy namespaces "
                "configured on the memory resource, so they cannot be inferred. "
                'Example: {"long_term": "/preferences/{actor_id}"}.'
            )

        return cls(
            memory_id=memory_id,
            namespaces=namespaces,
            region=config.get("region"),
            **(config.get("boto3_kwargs") or {}),
        )

    def __init__(
        self,
        *,
        memory_id: str,
        namespaces: Mapping[Any, Any],
        region: Optional[str] = None,
        store: Any = None,
        **boto3_kwargs: Any,
    ):
        # Fail fast on bad config rather than raising during a live call.
        if not isinstance(memory_id, str) or not memory_id.strip():
            raise ValueError("memory_id must be a non-empty string.")
        if not isinstance(namespaces, Mapping):
            raise ValueError(
                "namespaces must be a mapping (dict or similar). "
                f"Got {type(namespaces).__name__}."
            )

        self.memory_id = memory_id
        self.namespaces = self._normalize_namespaces(namespaces)

        # Injectable for tests/fakes; otherwise opens a real AWS client.
        self.store = (
            store if store is not None else self._build_store(region, boto3_kwargs)
        )

    def _build_store(self, region: Optional[str], boto3_kwargs: dict[str, Any]) -> Any:
        """Build the underlying langgraph-checkpoint-aws store."""
        try:
            from langgraph_checkpoint_aws import AgentCoreMemoryStore as _Store
        except ImportError as exc:
            raise ImportError(
                "AgentCoreMemoryStore requires 'langgraph-checkpoint-aws'."
            ) from exc

        if "region_name" not in boto3_kwargs:
            resolved_region = region
            if not resolved_region:
                try:
                    import boto3
                except ImportError as exc:
                    raise ImportError(
                        "AgentCoreMemoryStore requires 'boto3' to determine AWS region."
                    ) from exc
                resolved_region = boto3.Session().region_name

            if not resolved_region:
                raise ValueError(
                    "AWS region must be provided via store config or environment "
                    "for AgentCoreMemoryStore."
                )
            boto3_kwargs = {**boto3_kwargs, "region_name": resolved_region}

        return _Store(memory_id=self.memory_id, **boto3_kwargs)

    @staticmethod
    def _normalize_namespaces(
        namespaces: Mapping[Any, Any],
    ) -> dict[MemoryType, tuple[str, ...]]:
        """Coerce the namespace config into {MemoryType: (template, ...)} and validate."""
        normalized: dict[MemoryType, tuple[str, ...]] = {}
        for raw_type, raw_templates in namespaces.items():
            # MemoryType(x) accepts an existing MemoryType unchanged, so no
            # isinstance pre-check is needed.
            try:
                memory_type = MemoryType(raw_type)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Invalid memory type {raw_type!r} in namespaces. "
                    f"Expected one of {[mt.value for mt in MemoryType]}."
                ) from exc

            if isinstance(raw_templates, str):
                templates: Sequence[str] = (raw_templates,)
            elif isinstance(raw_templates, (list, tuple)):
                templates = tuple(raw_templates)
            else:
                raise ValueError(
                    f"Namespace for {memory_type.value} must be a string or a "
                    f"list/tuple of strings, got {type(raw_templates).__name__}."
                )

            if not templates or not all(isinstance(t, str) and t for t in templates):
                raise ValueError(
                    f"Namespace for {memory_type.value} must contain at least one "
                    "non-empty template string."
                )

            for template in templates:
                # Reject unknown/malformed placeholders at construction time.
                for _, field, format_spec, conversion in Formatter().parse(template):
                    if field is None:
                        continue
                    if format_spec or conversion:
                        raise ValueError(
                            f"Namespace template {template!r} uses a format spec or "
                            f"conversion on {{{field}}}. Only plain {{{field}}} "
                            "placeholders are supported."
                        )
                    if field not in _SUPPORTED_PLACEHOLDERS:
                        raise ValueError(
                            f"Unknown placeholder {{{field}}} in namespace template "
                            f"{template!r}. Supported placeholders: "
                            f"{sorted(_SUPPORTED_PLACEHOLDERS)}."
                        )
                # Reject purely-slash templates and whitespace-only segments;
                # both would resolve to an unscoped root namespace.
                labels = [s for s in template.split("/") if s]
                if not labels or any(not seg.strip() for seg in labels):
                    raise ValueError(
                        f"Namespace template {template!r} contains no usable path "
                        "segments or contains a whitespace-only segment."
                    )

            normalized[memory_type] = tuple(templates)

        if not normalized:
            raise ValueError("namespaces must contain at least one memory type.")
        return normalized

    def write_memory(self, entries: List[MemoryEntry]) -> None:
        """Write memory entries to AgentCore as conversational events.

        Events go to (actor_id, session_id); the AWS strategy decides where
        extraction lands. task_id, metadata, importance, and original timestamps
        are not forwarded. Input order is preserved within the batch but event
        ordering is not guaranteed. Extraction is asynchronous — a successful
        write does not mean the record is immediately searchable.
        """
        if not entries:
            return

        from langgraph.store.base import PutOp

        ops = []
        for entry in entries:
            if not (entry.content or "").strip():
                logger.debug(
                    "Skipping memory entry %s with empty content.", entry.record_id
                )
                continue
            if not entry.session_id:
                raise ValueError(
                    "MemoryEntry.session_id is required to write to AgentCore Memory."
                )
            # Same single-segment guarantee as the read-path namespace values.
            _validate_identity_value("session_id", entry.session_id)
            actor_id = self._resolve_actor_id(entry.user_id)
            # Via PutOp, not store.put(): put() rejects namespace labels
            # containing periods, which would reject email user IDs.
            ops.append(
                PutOp(
                    (actor_id, entry.session_id),
                    entry.record_id,
                    {"message": self._message_from_entry(entry)},
                )
            )

        if not ops:
            return

        from langgraph.store.base import InvalidNamespaceError

        try:
            self.store.batch(ops)
        except InvalidNamespaceError as exc:
            # batch(PutOp) should skip the periods-in-labels check, but if it
            # starts validating, surface a clear cause instead of a raw label error.
            raise RuntimeError(
                f"AgentCore store rejected an actor/session namespace: {exc}"
            ) from exc

    @staticmethod
    def _message_from_entry(entry: MemoryEntry) -> BaseMessage:
        """Convert a MemoryEntry into the message type AgentCore's event conversion expects."""
        metadata = entry.metadata or {}
        # None means absent → default to "human". Any other non-string or
        # unrecognised value is a caller bug and raises explicitly.
        role = metadata.get("role")
        if role is None:
            role = "human"
        if not isinstance(role, str) or role not in _ROLE_TO_MESSAGE:
            raise ValueError(
                f"Unsupported metadata['role'] {role!r} on memory entry "
                f"{entry.record_id}; expected one of {sorted(_ROLE_TO_MESSAGE)} "
                "or no role at all."
            )
        message_cls = _ROLE_TO_MESSAGE[role]

        if message_cls is ToolMessage:
            return ToolMessage(
                content=entry.content,
                tool_call_id=metadata.get("tool_call_id") or entry.record_id,
            )
        return message_cls(content=entry.content)

    def read_memories(
        self,
        query: Optional[str] = None,
        *,
        limit: int = 10,
        session_id: Optional[str] = None,
        task_id: Optional[str] = None,
        user_id: Optional[str] = None,
        memory_type: Optional[MemoryType] = None,
        metadata: Optional[Mapping[str, Any]] = None,
        **kwargs,
    ) -> List[MemoryEntry]:
        """Search extracted memory records for the given memory type.

        session_id/task_id/user_id are namespace-template inputs, not filters.
        A query string is required. A non-empty ``metadata`` raises rather than
        being silently ignored; None and {} are accepted as "no filter", because
        MemoryContextProvider forwards TurnRequest.metadata, which defaults to
        an empty dict on every turn. Unknown kwargs always raise.
        """
        if metadata:
            raise NotImplementedError(
                f"AgentCoreMemoryStore does not support metadata filtering (got "
                f"{metadata!r}). session_id, task_id, and user_id are "
                "namespace-template inputs, not independent filters."
            )
        if kwargs:
            raise NotImplementedError(
                "AgentCoreMemoryStore does not support these read_memories "
                f"arguments: {sorted(kwargs)}."
            )

        if limit <= 0:
            return []

        if not query or not query.strip():
            logger.debug(
                "AgentCoreMemoryStore.read_memories requires a query; returning []."
            )
            return []

        resolved_type = memory_type or MemoryType.LONG_TERM
        templates = self.namespaces.get(resolved_type)
        if not templates:
            logger.debug(
                "No AgentCore namespace configured for memory type %s; returning [].",
                resolved_type.value,
            )
            return []

        actor_id = self._resolve_actor_id(user_id)
        # Keep actor_id and user_id separate: a template expecting {user_id}
        # should skip rather than silently resolve to a different identity.
        values = {
            "actor_id": actor_id,
            "user_id": user_id,
            "session_id": session_id,
            "task_id": task_id,
        }

        # Deduplicate across namespaces, keeping the best-scoring occurrence.
        # key → (rank, item, namespace, template); rank uses _UNSCORED_RELEVANCE
        # when the backend gives no score.
        best: dict[str, tuple[float, Any, tuple[str, ...], str]] = {}

        for template in templates:
            namespace = self._render_namespace(template, values)
            if namespace is None:
                continue

            items = self.store.search(namespace, query=query, limit=limit)
            for item in items or []:
                rank = _relevance_of(item)
                if rank is None:
                    rank = _UNSCORED_RELEVANCE
                if item.key not in best or rank > best[item.key][0]:
                    best[item.key] = (rank, item, namespace, template)

        ranked = sorted(best.values(), key=lambda t: t[0], reverse=True)[:limit]
        return [
            self._entry_from_item(
                item,
                memory_type=resolved_type,
                actor_id=actor_id,
                namespace_template=template,
                namespace=namespace,
            )
            for _, item, namespace, template in ranked
        ]

    @staticmethod
    def _resolve_actor_id(user_id: Optional[str]) -> str:
        """Return the AgentCore actor ID for the given call identity."""
        if not user_id:
            raise ValueError(
                "AgentCoreMemoryStore requires a user_id to use as the AgentCore "
                "actor ID. The actor ID groups written events; it does not by "
                "itself isolate reads (the namespace template does that), so "
                "caller identity must be trusted upstream."
            )
        return _validate_identity_value("user_id", user_id)

    @staticmethod
    def _render_namespace(
        template: str, values: Mapping[str, Optional[str]]
    ) -> Optional[tuple[str, ...]]:
        """Render a namespace template to the tuple BaseStore expects.

        Returns None when any required placeholder is missing, so the caller
        skips rather than querying a partial path. Placeholder names are
        already validated at construction, so only value-level checks run here.
        """
        fields = {field for _, field, _, _ in Formatter().parse(template) if field}
        for field in fields:
            v = values.get(field)
            if v is None or v == "":
                logger.debug(
                    "Cannot render AgentCore namespace %r: missing value for {%s}.",
                    template,
                    field,
                )
                return None
            _validate_identity_value(field, v)
        return tuple(s for s in template.format(**values).split("/") if s)

    @staticmethod
    def _entry_from_item(
        item: Any,
        *,
        memory_type: MemoryType,
        actor_id: str,
        namespace_template: str,
        namespace: tuple[str, ...],
    ) -> MemoryEntry:
        """Convert an AgentCore SearchItem into a MemoryEntry.

        Relevance goes into metadata, not importance_score, because it is
        query-dependent — the same record should not look more or less
        "important" based on which query happened to surface it.
        """
        value = item.value or {}

        # actor_id is call context, not record ownership; stays in metadata.
        metadata: dict[str, Any] = {
            "source": "agentcore",
            "agentcore_query_actor_id": actor_id,
            "agentcore_namespace_template": namespace_template,
            "agentcore_namespace": "/".join(namespace),
            "memory_record_id": item.key,
        }
        if value.get("memory_strategy_id"):
            metadata["memory_strategy_id"] = value["memory_strategy_id"]
        if value.get("namespaces"):
            metadata["agentcore_record_namespaces"] = value["namespaces"]
        # Absent (not 0.0) so downstream can distinguish "unscored" from "scored 0".
        relevance_score = _relevance_of(item)
        if relevance_score is not None:
            metadata["relevance_score"] = relevance_score

        timestamp = item.created_at or datetime.now(timezone.utc)
        if timestamp.tzinfo is not None:
            timestamp = timestamp.astimezone().replace(tzinfo=None)

        return MemoryEntry(
            record_id=item.key,
            session_id="",
            task_id=None,
            user_id=None,
            content=value.get("content", ""),
            metadata=metadata,
            timestamp=timestamp,
            memory_type=memory_type,
            last_accessed=datetime.now(),
        )

    def delete_memory(self, record_id: str) -> bool:
        """Delete one extracted memory record by its AgentCore record ID.

        Goes straight to the boto3 client (the wrapper's PutOp delete path is
        a no-op). Does not delete the originating conversational event, so the
        fact can be re-extracted. Doesn't check namespaces or caller identity -
        deletes any record the resource-level credentials can reach; callers
        serving multiple users must authorize upstream.
        """
        client = getattr(self.store, "client", None)
        if client is None:
            # Injected store (test fake) may not expose a raw client.
            logger.warning(
                "Underlying AgentCore store exposes no boto3 client; record %s "
                "was not deleted.",
                record_id,
            )
            return False

        from botocore.exceptions import ClientError

        try:
            client.delete_memory_record(
                memoryId=self.memory_id, memoryRecordId=record_id
            )
        except ClientError as exc:
            # ResourceNotFoundException: record/resource missing or ID never existed.
            if exc.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                logger.warning(
                    "AgentCore reported no such resource while deleting record %s; "
                    "nothing was deleted (the record or the memory resource may not "
                    "exist).",
                    record_id,
                )
                return False
            raise
        return True

    def clear_memories(self, memory_type: Optional[MemoryType] = None) -> None:
        raise NotImplementedError(
            "AgentCoreMemoryStore does not implement clear_memories "
            f"(requested type: {memory_type.value if memory_type else 'all'}). "
            "Delete individual records with delete_memory(record_id)."
        )
