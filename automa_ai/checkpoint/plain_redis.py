from __future__ import annotations

import base64
import json
import random
import time
from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from typing import Any
from urllib.parse import quote

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    SerializerProtocol,
    get_checkpoint_id,
    get_checkpoint_metadata,
)
from redis import Redis
from redis.exceptions import ResponseError

from automa_ai.checkpoint.defaults import (
    DEFAULT_REDIS_CHECKPOINT_TTL_SECONDS,
    DEFAULT_REDIS_HEALTH_CHECK_INTERVAL,
    DEFAULT_REDIS_MAX_CHECKPOINTS_PER_THREAD,
    DEFAULT_REDIS_REFRESH_TTL_ON_READ,
    DEFAULT_REDIS_RETRY_ON_TIMEOUT,
    DEFAULT_REDIS_SOCKET_CONNECT_TIMEOUT,
    DEFAULT_REDIS_SOCKET_TIMEOUT,
)

_BLOB_KEYS_FIELD = "blob_keys"
_RETENTION_STEP_FIELD = "retention_step"


def _quote_key_part(value: str | int | float) -> str:
    return quote(str(value), safe="")


def _decode_redis_str(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _encode_typed(value: tuple[str, bytes]) -> dict[str, Any]:
    return {
        "type": value[0],
        "payload": base64.b64encode(value[1]).decode("ascii"),
    }


def _decode_typed(data: dict[str, Any]) -> tuple[str, bytes]:
    return data["type"], base64.b64decode(data["payload"])


class PlainRedisSaver(
    BaseCheckpointSaver[str], AbstractContextManager, AbstractAsyncContextManager
):
    """Redis checkpointer that relies only on core Redis commands.

    This saver is intentionally a bounded hot-session cache. When
    ``max_checkpoints_per_thread`` is enabled, pruning keeps the newest logical
    LangGraph step groups based on checkpoint metadata rather than counting raw
    checkpoint records. Applications that need arbitrary historical replay
    should raise that retention value or disable pruning.

    Step-group retention is not a strict record-count or byte-count cap: a very
    busy graph step can still retain many checkpoint records inside the retained
    step window. TTL and Redis maxmemory policy remain the primary memory
    controls; step pruning is a resume-friendly backstop for active sessions.

    Redis Cluster mode is intentionally not supported. Checkpoint lifecycle
    operations touch the checkpoint record, pending writes, index keys, and blob
    keys for one logical thread. In cluster-mode-enabled Redis those keys can
    land in different hash slots and raise CROSSSLOT errors. Deploy this saver
    on a single-shard Redis/Valkey target, such as ElastiCache cluster mode
    disabled with replicas.
    """

    def __init__(
        self,
        redis_url: str | None = None,
        *,
        redis_client: Redis | None = None,
        serde: SerializerProtocol | None = None,
        key_prefix: str = "automa_ai:checkpoint",
        checkpoint_ttl_seconds: int | None = DEFAULT_REDIS_CHECKPOINT_TTL_SECONDS,
        max_checkpoints_per_thread: int | None = (
            DEFAULT_REDIS_MAX_CHECKPOINTS_PER_THREAD
        ),
        refresh_ttl_on_read: bool = DEFAULT_REDIS_REFRESH_TTL_ON_READ,
        socket_timeout: float | None = DEFAULT_REDIS_SOCKET_TIMEOUT,
        socket_connect_timeout: float | None = DEFAULT_REDIS_SOCKET_CONNECT_TIMEOUT,
        health_check_interval: int | None = DEFAULT_REDIS_HEALTH_CHECK_INTERVAL,
        retry_on_timeout: bool = DEFAULT_REDIS_RETRY_ON_TIMEOUT,
    ) -> None:
        super().__init__(serde=serde)
        if redis_url is None and redis_client is None:
            raise ValueError("Either redis_url or redis_client must be provided.")
        self._redis = redis_client or self._build_redis_client(
            redis_url=redis_url,
            socket_timeout=socket_timeout,
            socket_connect_timeout=socket_connect_timeout,
            health_check_interval=health_check_interval,
            retry_on_timeout=retry_on_timeout,
        )
        self._owns_client = redis_client is None
        self._key_prefix = key_prefix.rstrip(":")
        self._checkpoint_ttl_seconds = checkpoint_ttl_seconds
        self._max_checkpoint_steps_per_thread = max_checkpoints_per_thread
        self._refresh_ttl_on_read = refresh_ttl_on_read

    @staticmethod
    def _build_redis_client(
        *,
        redis_url: str,
        socket_timeout: float | None,
        socket_connect_timeout: float | None,
        health_check_interval: int | None,
        retry_on_timeout: bool,
    ) -> Redis:
        """Create a Redis client with production-safe connection defaults.

        Long-running agent services should not wait indefinitely on stalled
        Redis sockets, and health checks help refresh pooled connections after
        ElastiCache failovers. Advanced TLS/IAM/client customization should use
        the ``redis_client`` injection path instead of ``redis_url``.

        Use this helper only for non-clustered Redis clients. Redis Cluster
        would need a different key layout with hash tags so all per-thread keys
        are assigned to the same hash slot.
        """
        return Redis.from_url(
            redis_url,
            socket_timeout=socket_timeout,
            socket_connect_timeout=socket_connect_timeout,
            health_check_interval=health_check_interval,
            retry_on_timeout=retry_on_timeout,
        )

    def __enter__(self) -> "PlainRedisSaver":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool | None:
        self.close()
        return None

    async def __aenter__(self) -> "PlainRedisSaver":
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> bool | None:
        self.close()
        return None

    def setup(self) -> None:
        self._redis.ping()

    def close(self) -> None:
        if self._owns_client:
            self._redis.close()

    def _threads_key(self) -> str:
        return f"{self._key_prefix}:threads"

    def _checkpoint_sequence_key(self, thread_id: str, checkpoint_ns: str) -> str:
        return (
            f"{self._key_prefix}:thread:{_quote_key_part(thread_id)}"
            f":ns:{_quote_key_part(checkpoint_ns)}:checkpoint_seq"
        )

    def _namespaces_key(self, thread_id: str) -> str:
        return f"{self._key_prefix}:thread:{_quote_key_part(thread_id)}:namespaces"

    def _checkpoint_index_key(self, thread_id: str, checkpoint_ns: str) -> str:
        return (
            f"{self._key_prefix}:thread:{_quote_key_part(thread_id)}"
            f":ns:{_quote_key_part(checkpoint_ns)}:checkpoints"
        )

    def _checkpoint_key(
        self, thread_id: str, checkpoint_ns: str, checkpoint_id: str
    ) -> str:
        return (
            f"{self._key_prefix}:thread:{_quote_key_part(thread_id)}"
            f":ns:{_quote_key_part(checkpoint_ns)}:cp:{_quote_key_part(checkpoint_id)}"
        )

    def _writes_key(
        self, thread_id: str, checkpoint_ns: str, checkpoint_id: str
    ) -> str:
        return f"{self._checkpoint_key(thread_id, checkpoint_ns, checkpoint_id)}:writes"

    def _blob_key(
        self,
        thread_id: str,
        checkpoint_ns: str,
        channel: str,
        version: str | int | float,
    ) -> str:
        return (
            f"{self._key_prefix}:thread:{_quote_key_part(thread_id)}"
            f":ns:{_quote_key_part(checkpoint_ns)}"
            f":blob:{_quote_key_part(channel)}:{_quote_key_part(version)}"
        )

    def _expire_keys(self, *keys: str) -> None:
        """Apply the idle-session TTL to Redis keys that were just used.

        The pipeline may include several keys for one thread. This is fine for a
        single-shard Redis deployment, but it is one reason ``redis_plain`` does
        not support Redis Cluster mode without a future hash-tagged key layout.
        """
        if not self._checkpoint_ttl_seconds or not keys:
            return
        pipe = self._redis.pipeline()
        for key in keys:
            pipe.expire(key, self._checkpoint_ttl_seconds)
        pipe.execute()

    def _checkpoint_blob_keys(
        self, thread_id: str, checkpoint_ns: str, checkpoint: Checkpoint
    ) -> list[str]:
        """Return blob keys referenced by a checkpoint's channel versions.

        LangGraph stores checkpoint metadata separately from channel payloads.
        The ``channel_versions`` map is the authoritative list of payload blobs
        a checkpoint needs in order to be rehydrated.
        """
        return [
            self._blob_key(thread_id, checkpoint_ns, channel, version)
            for channel, version in checkpoint.get("channel_versions", {}).items()
        ]

    def _touch_thread_indexes(self, thread_id: str, checkpoint_ns: str) -> None:
        """Refresh TTLs for the index keys that let us find a thread later."""
        self._record_thread_activity(thread_id)
        self._expire_keys(
            self._namespaces_key(thread_id),
            self._checkpoint_index_key(thread_id, checkpoint_ns),
            self._checkpoint_sequence_key(thread_id, checkpoint_ns),
        )

    def _record_thread_activity(self, thread_id: str) -> None:
        """Record the thread in a bounded global index.

        Redis cannot expire individual SET members. A sorted set lets us prune
        inactive thread ids by score on later activity, so the global index does
        not grow forever while the service is busy.
        """
        now = time.time()
        try:
            self._redis.zadd(self._threads_key(), {thread_id: now})
        except ResponseError as exc:
            if "WRONGTYPE" not in str(exc):
                raise
            # Older PlainRedisSaver versions used a SET at this key. Convert it
            # lazily so deployments can upgrade without an external migration.
            # Read members before deleting the SET; otherwise older threads stay
            # resumable by direct thread_id but disappear from list(None).
            try:
                existing_members = self._redis.smembers(self._threads_key())
            except ResponseError:
                existing_members = []
            mapping = {
                _decode_redis_str(raw_thread_id): now
                for raw_thread_id in existing_members
            }
            mapping[thread_id] = now
            self._redis.delete(self._threads_key())
            self._redis.zadd(self._threads_key(), mapping)

        if self._checkpoint_ttl_seconds:
            self._redis.zremrangebyscore(
                self._threads_key(), "-inf", now - self._checkpoint_ttl_seconds
            )

    def _thread_ids(self) -> list[str]:
        """Return known thread ids and migrate the old SET index if present."""
        try:
            raw_thread_ids = self._redis.zrange(self._threads_key(), 0, -1)
        except ResponseError as exc:
            if "WRONGTYPE" not in str(exc):
                raise
            raw_thread_ids = self._redis.smembers(self._threads_key())
            self._redis.delete(self._threads_key())
            for raw_thread_id in raw_thread_ids:
                self._record_thread_activity(_decode_redis_str(raw_thread_id))
        return sorted(_decode_redis_str(item) for item in raw_thread_ids)

    def _touch_checkpoint(
        self,
        thread_id: str,
        checkpoint_ns: str,
        checkpoint_id: str,
        checkpoint: Checkpoint | None = None,
        blob_keys: list[str] | None = None,
    ) -> None:
        """Refresh TTLs for one checkpoint and the indexes that point to it.

        Passing ``checkpoint`` also refreshes the payload blobs referenced by
        that checkpoint. Passing ``blob_keys`` lets pruning refresh retained
        records without deserializing checkpoint payloads.
        """
        keys = [
            self._checkpoint_key(thread_id, checkpoint_ns, checkpoint_id),
            self._writes_key(thread_id, checkpoint_ns, checkpoint_id),
        ]
        if checkpoint is not None:
            keys.extend(self._checkpoint_blob_keys(thread_id, checkpoint_ns, checkpoint))
        elif blob_keys is not None:
            keys.extend(blob_keys)

        self._expire_keys(*keys)
        self._touch_thread_indexes(thread_id, checkpoint_ns)

    def _load_checkpoint_sidecar(
        self, thread_id: str, checkpoint_ns: str, checkpoint_id: str
    ) -> tuple[str, list[str]] | None:
        """Load pruning sidecar fields without deserializing checkpoint payloads.

        New records store their retention step and blob key list as small hash
        fields. Older records may not have them; for those, fall back to the
        serialized checkpoint once and let normal writes/pruning eventually age
        them out.
        """
        raw_step, raw_blob_keys = self._redis.hmget(
            self._checkpoint_key(thread_id, checkpoint_ns, checkpoint_id),
            _RETENTION_STEP_FIELD,
            _BLOB_KEYS_FIELD,
        )
        if raw_step is not None and raw_blob_keys is not None:
            return (
                _decode_redis_str(raw_step),
                json.loads(_decode_redis_str(raw_blob_keys)),
            )

        record = self._load_checkpoint_record_without_blobs(
            thread_id, checkpoint_ns, checkpoint_id
        )
        if record is None:
            return None
        checkpoint, metadata = record
        return (
            self._checkpoint_step_key(checkpoint_id, metadata),
            self._checkpoint_blob_keys(thread_id, checkpoint_ns, checkpoint),
        )

    def _load_checkpoint_without_blobs(
        self, thread_id: str, checkpoint_ns: str, checkpoint_id: str
    ) -> Checkpoint | None:
        """Load checkpoint metadata without hydrating channel payload blobs.

        Pruning only needs the ``channel_versions`` references. Avoiding full
        blob deserialization keeps cleanup cheaper and prevents missing stale
        blobs from making retention decisions fail.
        """
        record = self._load_checkpoint_record_without_blobs(
            thread_id, checkpoint_ns, checkpoint_id
        )
        if record is None:
            return None
        checkpoint, _ = record
        return checkpoint

    def _load_checkpoint_record_without_blobs(
        self, thread_id: str, checkpoint_ns: str, checkpoint_id: str
    ) -> tuple[Checkpoint, CheckpointMetadata] | None:
        """Load checkpoint and metadata without channel payload blobs."""
        raw = self._redis.hgetall(
            self._checkpoint_key(thread_id, checkpoint_ns, checkpoint_id)
        )
        if not raw:
            return None

        checkpoint = self.serde.loads_typed(
            (
                _decode_redis_str(
                    raw.get(b"checkpoint_type", raw.get("checkpoint_type"))
                ),
                raw.get(b"checkpoint_payload", raw.get("checkpoint_payload", b"")),
            )
        )
        metadata = self.serde.loads_typed(
            (
                _decode_redis_str(raw.get(b"metadata_type", raw.get("metadata_type"))),
                raw.get(b"metadata_payload", raw.get("metadata_payload", b"")),
            )
        )
        return checkpoint, metadata

    @staticmethod
    def _checkpoint_step_key(
        checkpoint_id: str, metadata: CheckpointMetadata
    ) -> str:
        """Return the logical retention group for a checkpoint.

        LangGraph metadata carries ``step`` across the checkpoints produced
        inside one logical graph step/user turn. When that metadata is absent,
        fall back to the checkpoint id so pruning degrades to raw checkpoint
        retention for unknown checkpoint formats.
        """
        step = metadata.get("step")
        if step is None:
            return f"checkpoint:{checkpoint_id}"
        return json.dumps(step, sort_keys=True, separators=(",", ":"))

    def _prune_checkpoints(self, thread_id: str, checkpoint_ns: str) -> None:
        """Keep newest logical step groups for a thread and delete older records.

        This bounds Redis growth per active session. Blob deletion is handled
        with extra care because newer checkpoints can still reference channel
        payloads first written by older checkpoints. Pruning also bounds
        LangGraph time-travel/replay to the retained checkpoint window.

        This is not a strict record-count cap. All checkpoints in a retained
        step are kept, so a pathological single step can still produce many
        retained records until TTL or Redis eviction handles them.

        The delete step can remove checkpoint, writes, and blob keys together.
        That multi-key lifecycle is deliberate for simple single-shard Redis and
        is not compatible with ElastiCache cluster mode enabled.
        """
        if not self._max_checkpoint_steps_per_thread:
            return

        index_key = self._checkpoint_index_key(thread_id, checkpoint_ns)
        # Scores are Redis sequence values, so zrevrange returns newest
        # checkpoints first without depending on wall-clock behavior.
        checkpoint_ids = [
            _decode_redis_str(raw_checkpoint_id)
            for raw_checkpoint_id in self._redis.zrevrange(index_key, 0, -1)
        ]

        sidecars_by_id: dict[str, tuple[str, list[str]] | None] = {}
        retained_step_keys: set[str] = set()
        retained_ids: list[str] = []
        stale_ids: list[str] = []

        for checkpoint_id in checkpoint_ids:
            sidecar = self._load_checkpoint_sidecar(
                thread_id, checkpoint_ns, checkpoint_id
            )
            sidecars_by_id[checkpoint_id] = sidecar
            if sidecar is None:
                stale_ids.append(checkpoint_id)
                continue

            step_key, _ = sidecar
            if step_key not in retained_step_keys:
                if (
                    len(retained_step_keys)
                    >= self._max_checkpoint_steps_per_thread
                ):
                    stale_ids.append(checkpoint_id)
                    continue
                retained_step_keys.add(step_key)
            retained_ids.append(checkpoint_id)

        if not stale_ids:
            return

        # Compute retained blob references before deleting stale checkpoint records.
        # This is what prevents pruning from corrupting the latest checkpoint.
        retained_blob_keys: set[str] = set()
        for checkpoint_id in retained_ids:
            sidecar = sidecars_by_id.get(checkpoint_id)
            if sidecar is None:
                continue
            _, blob_keys = sidecar
            retained_blob_keys.update(blob_keys)
            self._touch_checkpoint(
                thread_id, checkpoint_ns, checkpoint_id, blob_keys=blob_keys
            )

        stale_blob_keys: set[str] = set()
        keys_to_delete: list[str] = []
        for checkpoint_id in stale_ids:
            sidecar = sidecars_by_id.get(checkpoint_id)
            if sidecar is not None:
                _, blob_keys = sidecar
                # LangGraph checkpoints may point at channel versions written by
                # older checkpoints. Delete a blob only when no retained checkpoint
                # still references that exact channel/version key.
                stale_blob_keys.update(blob_keys)

            keys_to_delete.extend(
                [
                    self._checkpoint_key(thread_id, checkpoint_ns, checkpoint_id),
                    self._writes_key(thread_id, checkpoint_ns, checkpoint_id),
                ]
            )

        # Set subtraction keeps any blob that is shared with retained checkpoints.
        blob_keys_to_delete = stale_blob_keys - retained_blob_keys
        all_keys_to_delete = keys_to_delete + list(blob_keys_to_delete)
        if all_keys_to_delete:
            self._redis.delete(*all_keys_to_delete)
        self._redis.zrem(index_key, *stale_ids)

    def _load_blobs(
        self, thread_id: str, checkpoint_ns: str, versions: ChannelVersions
    ) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for channel, version in versions.items():
            blob = self._redis.hgetall(
                self._blob_key(thread_id, checkpoint_ns, channel, version)
            )
            if not blob:
                continue
            if _decode_redis_str(blob.get(b"empty", blob.get("empty", b"0"))) == "1":
                continue
            typed = (
                _decode_redis_str(blob.get(b"type", blob.get("type"))),
                blob.get(b"payload", blob.get("payload", b"")),
            )
            values[channel] = self.serde.loads_typed(typed)
        return values

    def _load_pending_writes(
        self, thread_id: str, checkpoint_ns: str, checkpoint_id: str
    ) -> list[tuple[str, str, Any]]:
        data = self._redis.hgetall(
            self._writes_key(thread_id, checkpoint_ns, checkpoint_id)
        )
        decoded: list[tuple[int, str, str, Any]] = []
        for raw_value in data.values():
            item = json.loads(_decode_redis_str(raw_value))
            typed = _decode_typed(item["value"])
            decoded.append(
                (
                    int(item["idx"]),
                    item["task_id"],
                    item["channel"],
                    self.serde.loads_typed(typed),
                )
            )
        decoded.sort(key=lambda item: (item[0], item[1], item[2]))
        return [(task_id, channel, value) for _, task_id, channel, value in decoded]

    def _get_checkpoint_tuple(
        self, thread_id: str, checkpoint_ns: str, checkpoint_id: str
    ) -> CheckpointTuple | None:
        raw = self._redis.hgetall(
            self._checkpoint_key(thread_id, checkpoint_ns, checkpoint_id)
        )
        if not raw:
            return None

        checkpoint = self.serde.loads_typed(
            (
                _decode_redis_str(
                    raw.get(b"checkpoint_type", raw.get("checkpoint_type"))
                ),
                raw.get(b"checkpoint_payload", raw.get("checkpoint_payload", b"")),
            )
        )
        metadata = self.serde.loads_typed(
            (
                _decode_redis_str(raw.get(b"metadata_type", raw.get("metadata_type"))),
                raw.get(b"metadata_payload", raw.get("metadata_payload", b"")),
            )
        )
        parent_checkpoint_id = _decode_redis_str(
            raw.get(b"parent_checkpoint_id", raw.get("parent_checkpoint_id", b""))
        )
        if parent_checkpoint_id == "":
            parent_checkpoint_id = None

        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": checkpoint_id,
                }
            },
            checkpoint={
                **checkpoint,
                "channel_values": self._load_blobs(
                    thread_id, checkpoint_ns, checkpoint["channel_versions"]
                ),
            },
            metadata=metadata,
            parent_config=(
                {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": parent_checkpoint_id,
                    }
                }
                if parent_checkpoint_id
                else None
            ),
            pending_writes=self._load_pending_writes(
                thread_id, checkpoint_ns, checkpoint_id
            ),
        )

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = get_checkpoint_id(config)

        if checkpoint_id is None:
            latest = self._redis.zrevrange(
                self._checkpoint_index_key(thread_id, checkpoint_ns), 0, 0
            )
            if not latest:
                return None
            checkpoint_id = _decode_redis_str(latest[0])
            result = self._get_checkpoint_tuple(thread_id, checkpoint_ns, checkpoint_id)
            if result is not None and self._refresh_ttl_on_read:
                self._touch_checkpoint(
                    thread_id, checkpoint_ns, checkpoint_id, result.checkpoint
                )
            return result

        result = self._get_checkpoint_tuple(thread_id, checkpoint_ns, checkpoint_id)
        if result is None:
            return None
        if self._refresh_ttl_on_read:
            self._touch_checkpoint(
                thread_id, checkpoint_ns, checkpoint_id, result.checkpoint
            )
        return result._replace(config=config)

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        thread_ids = (
            [config["configurable"]["thread_id"]]
            if config
            else self._thread_ids()
        )
        config_checkpoint_ns = (
            config["configurable"].get("checkpoint_ns") if config else None
        )
        config_checkpoint_id = get_checkpoint_id(config) if config else None
        before_checkpoint_id = get_checkpoint_id(before) if before else None

        remaining = limit
        for thread_id in thread_ids:
            namespaces = (
                [config_checkpoint_ns]
                if config_checkpoint_ns is not None
                else sorted(
                    _decode_redis_str(item)
                    for item in self._redis.smembers(self._namespaces_key(thread_id))
                )
            )

            for checkpoint_ns in namespaces:
                checkpoint_ids = self._redis.zrevrange(
                    self._checkpoint_index_key(thread_id, checkpoint_ns or ""), 0, -1
                )
                # Checkpoint ordering now comes from the Redis ZSET score, not
                # the checkpoint id. Treat ``before`` as a cursor in that ordered
                # stream and start yielding only after the cursor is encountered.
                passed_before = before_checkpoint_id is None
                for raw_checkpoint_id in checkpoint_ids:
                    checkpoint_id = _decode_redis_str(raw_checkpoint_id)
                    if not passed_before:
                        if checkpoint_id == before_checkpoint_id:
                            passed_before = True
                        continue
                    if config_checkpoint_id and checkpoint_id != config_checkpoint_id:
                        continue

                    item = self._get_checkpoint_tuple(
                        thread_id, checkpoint_ns or "", checkpoint_id
                    )
                    if item is None:
                        continue
                    if filter and not all(
                        item.metadata.get(query_key) == query_value
                        for query_key, query_value in filter.items()
                    ):
                        continue
                    if self._refresh_ttl_on_read:
                        self._touch_checkpoint(
                            thread_id,
                            checkpoint_ns or "",
                            checkpoint_id,
                            item.checkpoint,
                        )

                    yield item

                    if remaining is not None:
                        remaining -= 1
                        if remaining <= 0:
                            return

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        checkpoint_copy = checkpoint.copy()
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        values = checkpoint_copy.pop("channel_values")
        checkpoint_order = self._redis.incr(
            self._checkpoint_sequence_key(thread_id, checkpoint_ns)
        )

        for channel, version in new_versions.items():
            blob_key = self._blob_key(thread_id, checkpoint_ns, channel, version)
            if channel in values:
                value_type, value_payload = self.serde.dumps_typed(values[channel])
                self._redis.hset(
                    blob_key,
                    mapping={
                        "empty": "0",
                        "type": value_type,
                        "payload": value_payload,
                    },
                )
            else:
                self._redis.hset(blob_key, mapping={"empty": "1"})

        checkpoint_type, checkpoint_payload = self.serde.dumps_typed(checkpoint_copy)
        checkpoint_metadata = get_checkpoint_metadata(config, metadata)
        metadata_type, metadata_payload = self.serde.dumps_typed(checkpoint_metadata)
        blob_keys = self._checkpoint_blob_keys(thread_id, checkpoint_ns, checkpoint)
        self._redis.hset(
            self._checkpoint_key(thread_id, checkpoint_ns, checkpoint["id"]),
            mapping={
                "checkpoint_type": checkpoint_type,
                "checkpoint_payload": checkpoint_payload,
                "metadata_type": metadata_type,
                "metadata_payload": metadata_payload,
                "parent_checkpoint_id": config["configurable"].get("checkpoint_id", ""),
                _RETENTION_STEP_FIELD: self._checkpoint_step_key(
                    checkpoint["id"], checkpoint_metadata
                ),
                _BLOB_KEYS_FIELD: json.dumps(blob_keys),
            },
        )
        self._redis.zadd(
            self._checkpoint_index_key(thread_id, checkpoint_ns),
            {checkpoint["id"]: checkpoint_order},
        )
        self._redis.sadd(self._namespaces_key(thread_id), checkpoint_ns)
        self._touch_checkpoint(
            thread_id, checkpoint_ns, checkpoint["id"], blob_keys=blob_keys
        )
        self._prune_checkpoints(thread_id, checkpoint_ns)

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"]["checkpoint_id"]
        writes_key = self._writes_key(thread_id, checkpoint_ns, checkpoint_id)

        existing_fields = {
            _decode_redis_str(field) for field in self._redis.hkeys(writes_key)
        }
        for idx, (channel, value) in enumerate(writes):
            write_idx = WRITES_IDX_MAP.get(channel, idx)
            field = f"{_quote_key_part(task_id)}:{write_idx}"
            if write_idx >= 0 and field in existing_fields:
                continue

            serialized = json.dumps(
                {
                    "idx": write_idx,
                    "task_id": task_id,
                    "channel": channel,
                    "task_path": task_path,
                    "value": _encode_typed(self.serde.dumps_typed(value)),
                }
            )
            self._redis.hset(writes_key, field, serialized)
        checkpoint = self._load_checkpoint_without_blobs(
            thread_id, checkpoint_ns, checkpoint_id
        )
        if checkpoint is None:
            self._expire_keys(writes_key)
            self._touch_thread_indexes(thread_id, checkpoint_ns)
            return
        self._touch_checkpoint(thread_id, checkpoint_ns, checkpoint_id, checkpoint)

    def delete_thread(self, thread_id: str) -> None:
        namespaces = [
            _decode_redis_str(item)
            for item in self._redis.smembers(self._namespaces_key(thread_id))
        ]
        for checkpoint_ns in namespaces:
            index_key = self._checkpoint_index_key(thread_id, checkpoint_ns)
            checkpoint_ids = self._redis.zrange(index_key, 0, -1)
            for raw_checkpoint_id in checkpoint_ids:
                checkpoint_id = _decode_redis_str(raw_checkpoint_id)
                checkpoint_tuple = self._get_checkpoint_tuple(
                    thread_id, checkpoint_ns, checkpoint_id
                )
                if checkpoint_tuple is not None:
                    for channel, version in checkpoint_tuple.checkpoint[
                        "channel_versions"
                    ].items():
                        self._redis.delete(
                            self._blob_key(thread_id, checkpoint_ns, channel, version)
                        )
                self._redis.delete(
                    self._writes_key(thread_id, checkpoint_ns, checkpoint_id)
                )
                self._redis.delete(
                    self._checkpoint_key(thread_id, checkpoint_ns, checkpoint_id)
                )
            self._redis.delete(index_key)
            self._redis.delete(self._checkpoint_sequence_key(thread_id, checkpoint_ns))
        self._redis.delete(self._namespaces_key(thread_id))
        try:
            self._redis.zrem(self._threads_key(), thread_id)
        except ResponseError as exc:
            if "WRONGTYPE" not in str(exc):
                raise
            self._redis.srem(self._threads_key(), thread_id)

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        return self.get_tuple(config)

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        for item in self.list(config, filter=filter, before=before, limit=limit):
            yield item

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        return self.put(config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        self.put_writes(config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id: str) -> None:
        self.delete_thread(thread_id)

    def get_next_version(self, current: str | None, channel: None) -> str:
        if current is None:
            current_v = 0
        elif isinstance(current, int):
            current_v = current
        else:
            current_v = int(current.split(".")[0])
        next_v = current_v + 1
        next_h = random.random()
        return f"{next_v:032}.{next_h:016}"
