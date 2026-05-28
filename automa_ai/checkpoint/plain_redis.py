from __future__ import annotations

import base64
import json
import random
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
    """Redis checkpointer that relies only on core Redis commands."""

    def __init__(
        self,
        redis_url: str | None = None,
        *,
        redis_client: Redis | None = None,
        serde: SerializerProtocol | None = None,
        key_prefix: str = "automa_ai:checkpoint",
    ) -> None:
        super().__init__(serde=serde)
        if redis_url is None and redis_client is None:
            raise ValueError("Either redis_url or redis_client must be provided.")
        # valkey setup
        self._redis = redis_client or Redis.from_url(redis_url, ssl=True, decode_responses=False)
        self._owns_client = redis_client is None
        self._key_prefix = key_prefix.rstrip(":")

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
            return self._get_checkpoint_tuple(thread_id, checkpoint_ns, checkpoint_id)

        result = self._get_checkpoint_tuple(thread_id, checkpoint_ns, checkpoint_id)
        if result is None:
            return None
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
            else sorted(
                _decode_redis_str(item)
                for item in self._redis.smembers(self._threads_key())
            )
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
                for raw_checkpoint_id in checkpoint_ids:
                    checkpoint_id = _decode_redis_str(raw_checkpoint_id)
                    if config_checkpoint_id and checkpoint_id != config_checkpoint_id:
                        continue
                    if before_checkpoint_id and checkpoint_id >= before_checkpoint_id:
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
        metadata_type, metadata_payload = self.serde.dumps_typed(
            get_checkpoint_metadata(config, metadata)
        )
        self._redis.hset(
            self._checkpoint_key(thread_id, checkpoint_ns, checkpoint["id"]),
            mapping={
                "checkpoint_type": checkpoint_type,
                "checkpoint_payload": checkpoint_payload,
                "metadata_type": metadata_type,
                "metadata_payload": metadata_payload,
                "parent_checkpoint_id": config["configurable"].get("checkpoint_id", ""),
            },
        )
        self._redis.zadd(
            self._checkpoint_index_key(thread_id, checkpoint_ns),
            {checkpoint["id"]: 0},
        )
        self._redis.sadd(self._threads_key(), thread_id)
        self._redis.sadd(self._namespaces_key(thread_id), checkpoint_ns)

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
        self._redis.delete(self._namespaces_key(thread_id))
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
