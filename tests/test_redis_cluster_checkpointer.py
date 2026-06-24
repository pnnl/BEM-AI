from __future__ import annotations

from automa_ai.checkpoint import RedisClusterSaver


class DummyPipeline:
    def expire(self, *args, **kwargs) -> None:
        return None

    def execute(self) -> None:
        return None


class DummyRedis:
    def close(self) -> None:
        return None

    def pipeline(self) -> DummyPipeline:
        return DummyPipeline()


def test_redis_cluster_saver_uses_thread_hash_tags() -> None:
    saver = RedisClusterSaver(redis_client=DummyRedis())

    thread_id = "drafter:session-123"
    expected_tag = "{thread:drafter%3Asession-123}"

    checkpoint_key = saver._checkpoint_key(thread_id, "ns", "cp-1")
    writes_key = saver._writes_key(thread_id, "ns", "cp-1")
    index_key = saver._checkpoint_index_key(thread_id, "ns")
    sequence_key = saver._checkpoint_sequence_key(thread_id, "ns")
    blob_key = saver._blob_key(thread_id, "ns", "channel", "v1")

    for key in (checkpoint_key, writes_key, index_key, sequence_key, blob_key):
        assert expected_tag in key
