from __future__ import annotations

from redis.cluster import RedisCluster

from automa_ai.checkpoint.plain_redis import PlainRedisSaver, _quote_key_part


class RedisClusterSaver(PlainRedisSaver):
    """Redis Cluster-compatible checkpoint saver.

    This saver preserves the operational contract of ``PlainRedisSaver`` while
    assigning every per-thread key to the same Redis Cluster hash slot. It does
    that by embedding a stable hash tag derived from ``thread_id`` in all
    thread-scoped keys. Global bookkeeping keys that are touched one at a time
    remain untagged.
    """

    @staticmethod
    def _build_redis_client(
        *,
        redis_url: str,
        socket_timeout: float | None,
        socket_connect_timeout: float | None,
        health_check_interval: int | None,
        retry_on_timeout: bool,
    ) -> RedisCluster:
        return RedisCluster.from_url(
            redis_url,
            socket_timeout=socket_timeout,
            socket_connect_timeout=socket_connect_timeout,
            health_check_interval=health_check_interval,
            retry_on_timeout=retry_on_timeout,
        )

    @staticmethod
    def _thread_hash_tag(thread_id: str) -> str:
        return f"{{thread:{_quote_key_part(thread_id)}}}"

    def _checkpoint_sequence_key(self, thread_id: str, checkpoint_ns: str) -> str:
        return (
            f"{self._key_prefix}:thread:{self._thread_hash_tag(thread_id)}"
            f":ns:{_quote_key_part(checkpoint_ns)}:checkpoint_seq"
        )

    def _namespaces_key(self, thread_id: str) -> str:
        return (
            f"{self._key_prefix}:thread:{self._thread_hash_tag(thread_id)}:namespaces"
        )

    def _checkpoint_index_key(self, thread_id: str, checkpoint_ns: str) -> str:
        return (
            f"{self._key_prefix}:thread:{self._thread_hash_tag(thread_id)}"
            f":ns:{_quote_key_part(checkpoint_ns)}:checkpoints"
        )

    def _checkpoint_key(
        self, thread_id: str, checkpoint_ns: str, checkpoint_id: str
    ) -> str:
        return (
            f"{self._key_prefix}:thread:{self._thread_hash_tag(thread_id)}"
            f":ns:{_quote_key_part(checkpoint_ns)}:cp:{_quote_key_part(checkpoint_id)}"
        )

    def _blob_key(
        self,
        thread_id: str,
        checkpoint_ns: str,
        channel: str,
        version: str | int | float,
    ) -> str:
        return (
            f"{self._key_prefix}:thread:{self._thread_hash_tag(thread_id)}"
            f":ns:{_quote_key_part(checkpoint_ns)}"
            f":blob:{_quote_key_part(channel)}:{_quote_key_part(version)}"
        )
