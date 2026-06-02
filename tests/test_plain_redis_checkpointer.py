from __future__ import annotations

from collections import defaultdict

from langgraph.checkpoint.base import empty_checkpoint

from automa_ai.checkpoint import plain_redis
from automa_ai.checkpoint.defaults import DEFAULT_REDIS_MAX_CHECKPOINTS_PER_THREAD
from automa_ai.checkpoint import PlainRedisSaver


class FakeRedis:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[object, object]] = defaultdict(dict)
        self.sets: dict[str, set[object]] = defaultdict(set)
        self.zsets: dict[str, dict[object, float]] = defaultdict(dict)
        self.ttls: dict[str, int] = {}
        self.strings: dict[str, int] = {}
        self.hgetall_calls = 0
        self.closed = False

    def ping(self) -> bool:
        return True

    def close(self) -> None:
        self.closed = True

    def hset(self, key: str, field=None, value=None, mapping=None) -> int:
        if mapping is not None:
            self.hashes[key].update(mapping)
            return len(mapping)
        self.hashes[key][field] = value
        return 1

    def hgetall(self, key: str) -> dict[object, object]:
        self.hgetall_calls += 1
        return dict(self.hashes.get(key, {}))

    def hkeys(self, key: str) -> list[object]:
        return list(self.hashes.get(key, {}).keys())

    def hmget(self, key: str, *fields: object) -> list[object | None]:
        data = self.hashes.get(key, {})
        return [data.get(field) for field in fields]

    def zadd(self, key: str, mapping: dict[object, float]) -> int:
        self.zsets[key].update(mapping)
        return len(mapping)

    def zrem(self, key: str, *values: object) -> int:
        removed = 0
        for value in values:
            if value in self.zsets.get(key, {}):
                self.zsets[key].pop(value, None)
                removed += 1
        return removed

    def zremrangebyscore(self, key: str, min_score, max_score) -> int:
        min_value = float("-inf") if min_score == "-inf" else float(min_score)
        max_value = float("inf") if max_score == "+inf" else float(max_score)
        to_remove = [
            value
            for value, score in self.zsets.get(key, {}).items()
            if min_value <= score <= max_value
        ]
        return self.zrem(key, *to_remove)

    def zrange(self, key: str, start: int, stop: int) -> list[object]:
        items = [
            item
            for item, _ in sorted(
                self.zsets.get(key, {}).items(), key=lambda pair: pair[1]
            )
        ]
        return self._slice(items, start, stop)

    def zrevrange(self, key: str, start: int, stop: int) -> list[object]:
        items = [
            item
            for item, _ in sorted(
                self.zsets.get(key, {}).items(),
                key=lambda pair: pair[1],
                reverse=True,
            )
        ]
        return self._slice(items, start, stop)

    def sadd(self, key: str, *values: object) -> int:
        self.sets[key].update(values)
        return len(values)

    def smembers(self, key: str) -> set[object]:
        return set(self.sets.get(key, set()))

    def srem(self, key: str, *values: object) -> int:
        removed = 0
        for value in values:
            if value in self.sets.get(key, set()):
                self.sets[key].remove(value)
                removed += 1
        return removed

    def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            removed += int(key in self.hashes)
            self.hashes.pop(key, None)
            removed += int(key in self.sets)
            self.sets.pop(key, None)
            removed += int(key in self.zsets)
            self.zsets.pop(key, None)
            removed += int(key in self.strings)
            self.strings.pop(key, None)
            self.ttls.pop(key, None)
        return removed

    def incr(self, key: str) -> int:
        self.strings[key] = self.strings.get(key, 0) + 1
        return self.strings[key]

    def expire(self, key: str, ttl: int) -> bool:
        self.ttls[key] = ttl
        return True

    def pipeline(self):
        return self

    def execute(self) -> list:
        return []

    @staticmethod
    def _slice(items: list[object], start: int, stop: int) -> list[object]:
        if stop == -1:
            stop = len(items) - 1
        if not items or start >= len(items) or stop < start:
            return []
        return items[start : stop + 1]


def _build_checkpoint(*, value: str, version_seed: str) -> dict:
    checkpoint = empty_checkpoint()
    checkpoint["channel_values"] = {"messages": [value]}
    checkpoint["channel_versions"] = {"messages": version_seed}
    checkpoint["versions_seen"] = {}
    checkpoint["updated_channels"] = ["messages"]
    return checkpoint


def test_plain_redis_saver_round_trip_and_latest_lookup() -> None:
    client = FakeRedis()
    saver = PlainRedisSaver(
        redis_client=client,
        max_checkpoints_per_thread=DEFAULT_REDIS_MAX_CHECKPOINTS_PER_THREAD,
    )
    saver.setup()

    base_config = {"configurable": {"thread_id": "thread-1", "checkpoint_ns": ""}}

    checkpoint_one = _build_checkpoint(value="hello", version_seed="0001")
    config_one = saver.put(
        base_config,
        checkpoint_one,
        {"source": "input", "step": -1},
        checkpoint_one["channel_versions"],
    )
    saver.put_writes(config_one, [("custom", {"foo": "bar"})], task_id="task-1")

    checkpoint_two = _build_checkpoint(value="world", version_seed="0002")
    config_two = saver.put(
        config_one,
        checkpoint_two,
        {"source": "loop", "step": 0},
        checkpoint_two["channel_versions"],
    )

    latest = saver.get_tuple({"configurable": {"thread_id": "thread-1"}})
    assert latest is not None
    assert latest.checkpoint["id"] == checkpoint_two["id"]
    assert latest.checkpoint["channel_values"]["messages"] == ["world"]

    first = saver.get_tuple(config_one)
    assert first is not None
    assert first.checkpoint["channel_values"]["messages"] == ["hello"]
    assert first.pending_writes == [("task-1", "custom", {"foo": "bar"})]

    listed = list(saver.list({"configurable": {"thread_id": "thread-1"}}))
    assert [item.checkpoint["id"] for item in listed] == [
        checkpoint_two["id"],
        checkpoint_one["id"],
    ]

    saver.delete_thread("thread-1")
    assert saver.get_tuple({"configurable": {"thread_id": "thread-1"}}) is None


def test_plain_redis_saver_sets_ttl_and_prunes_old_checkpoint_steps() -> None:
    client = FakeRedis()
    saver = PlainRedisSaver(
        redis_client=client,
        checkpoint_ttl_seconds=60,
        max_checkpoints_per_thread=2,
    )
    base_config = {"configurable": {"thread_id": "thread-1", "checkpoint_ns": ""}}

    configs = []
    config = base_config
    for idx, step in enumerate([0, 1, 1, 2]):
        checkpoint = _build_checkpoint(value=f"value-{idx}", version_seed=f"000{idx}")
        config = saver.put(
            config,
            checkpoint,
            {"source": "loop", "step": step},
            checkpoint["channel_versions"],
        )
        configs.append(config)

    assert client.hgetall_calls == 0
    listed = list(saver.list({"configurable": {"thread_id": "thread-1"}}))
    assert [item.checkpoint["id"] for item in listed] == [
        configs[3]["configurable"]["checkpoint_id"],
        configs[2]["configurable"]["checkpoint_id"],
        configs[1]["configurable"]["checkpoint_id"],
    ]
    assert saver.get_tuple(configs[0]) is None
    assert client.ttls
    assert all(ttl == 60 for ttl in client.ttls.values())


def test_plain_redis_saver_thread_index_prunes_idle_members() -> None:
    client = FakeRedis()
    saver = PlainRedisSaver(redis_client=client, checkpoint_ttl_seconds=60)
    threads_key = saver._threads_key()

    client.zadd(threads_key, {"dead-thread": 1})
    saver._record_thread_activity("active-thread")

    assert "dead-thread" not in client.zsets[threads_key]
    assert "active-thread" in client.zsets[threads_key]


def test_plain_redis_saver_put_writes_refreshes_checkpoint_and_blob_ttls() -> None:
    client = FakeRedis()
    saver = PlainRedisSaver(redis_client=client, checkpoint_ttl_seconds=60)
    base_config = {"configurable": {"thread_id": "thread-1", "checkpoint_ns": ""}}

    checkpoint = _build_checkpoint(value="hello", version_seed="0001")
    config = saver.put(
        base_config,
        checkpoint,
        {"source": "input", "step": -1},
        checkpoint["channel_versions"],
    )
    client.ttls.clear()

    saver.put_writes(config, [("custom", {"foo": "bar"})], task_id="task-1")

    checkpoint_id = config["configurable"]["checkpoint_id"]
    assert client.ttls[
        saver._checkpoint_key("thread-1", "", checkpoint_id)
    ] == 60
    assert client.ttls[
        saver._blob_key("thread-1", "", "messages", "0001")
    ] == 60
    assert client.ttls[
        saver._writes_key("thread-1", "", checkpoint_id)
    ] == 60


def test_plain_redis_saver_builds_client_with_connection_resilience(monkeypatch) -> None:
    captured: dict[str, object] = {}
    client = FakeRedis()

    def fake_from_url(redis_url: str, **kwargs):
        captured["redis_url"] = redis_url
        captured.update(kwargs)
        return client

    monkeypatch.setattr(plain_redis.Redis, "from_url", fake_from_url)

    saver = PlainRedisSaver(
        redis_url="redis://localhost:6379",
        socket_timeout=3.0,
        socket_connect_timeout=2.0,
        health_check_interval=15,
        retry_on_timeout=False,
    )

    assert saver._redis is client
    assert captured == {
        "redis_url": "redis://localhost:6379",
        "socket_timeout": 3.0,
        "socket_connect_timeout": 2.0,
        "health_check_interval": 15,
        "retry_on_timeout": False,
    }
