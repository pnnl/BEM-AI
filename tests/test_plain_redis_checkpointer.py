from __future__ import annotations

from collections import defaultdict

from langgraph.checkpoint.base import empty_checkpoint

from automa_ai.checkpoint import PlainRedisSaver


class FakeRedis:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[object, object]] = defaultdict(dict)
        self.sets: dict[str, set[object]] = defaultdict(set)
        self.zsets: dict[str, dict[object, float]] = defaultdict(dict)
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
        return dict(self.hashes.get(key, {}))

    def hkeys(self, key: str) -> list[object]:
        return list(self.hashes.get(key, {}).keys())

    def zadd(self, key: str, mapping: dict[object, float]) -> int:
        self.zsets[key].update(mapping)
        return len(mapping)

    def zrange(self, key: str, start: int, stop: int) -> list[object]:
        items = sorted(self.zsets.get(key, {}))
        return self._slice(items, start, stop)

    def zrevrange(self, key: str, start: int, stop: int) -> list[object]:
        items = sorted(self.zsets.get(key, {}), reverse=True)
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
        return removed

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
    saver = PlainRedisSaver(redis_client=client)
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
