from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.store.base import SearchItem

from automa_ai.memory.agentcore_memory_store import AgentCoreMemoryStore
from automa_ai.memory.manager import DefaultMemoryManager
from automa_ai.memory.memory_types import MemoryEntry, MemoryType


class FakeAgentCoreStore:
    """Stand-in for langgraph_checkpoint_aws.AgentCoreMemoryStore."""

    def __init__(
        self,
        results: dict[tuple[str, ...], list[SearchItem]] | None = None,
        client=None,
    ):
        self.batches: list[list] = []
        self.searches: list[dict] = []
        self.results = results or {}
        # Exposed for delete_memory, which calls store.client directly.
        self.client = client

    def batch(self, ops) -> list[None]:
        ops = list(ops)
        self.batches.append(ops)
        return [None] * len(ops)

    def search(self, namespace_prefix, *, query=None, limit=10, **kwargs):
        self.searches.append(
            {"namespace": namespace_prefix, "query": query, "limit": limit}
        )
        return self.results.get(namespace_prefix, [])


def make_item(
    key: str, content: str, score: float | None, created_at=None
) -> SearchItem:
    created_at = created_at or datetime.now(timezone.utc)
    return SearchItem(
        namespace=("preferences", "user-1"),
        key=key,
        value={
            "content": content,
            "memory_strategy_id": "strategy-1",
            "namespaces": ["/preferences/user-1"],
        },
        created_at=created_at,
        updated_at=created_at,
        score=score,
    )


def build_store(fake=None, namespaces=None, **kwargs) -> AgentCoreMemoryStore:
    """Build a test store with sensible defaults."""
    fake = fake or FakeAgentCoreStore()
    namespaces = namespaces or {
        MemoryType.LONG_TERM: "/preferences/{actor_id}",
        MemoryType.EPISODIC: "/summaries/{actor_id}/{session_id}",
    }
    return AgentCoreMemoryStore(
        memory_id="mem-123", namespaces=namespaces, store=fake, **kwargs
    )


def write_entry(store, **overrides) -> None:
    """Write a single memory entry with test defaults."""
    defaults = {
        "session_id": "s1",
        "user_id": "user-1",
        "content": "hello",
        "metadata": {"role": "human"},
    }
    store.write_memory([MemoryEntry(**(defaults | overrides))])


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------


def test_from_config_requires_memory_id() -> None:
    with pytest.raises(ValueError, match="memory_id must be defined"):
        AgentCoreMemoryStore.from_config(
            {"namespaces": {"long_term": "/facts/{actor_id}"}}
        )


def test_from_config_requires_namespaces() -> None:
    with pytest.raises(ValueError, match="namespaces must be defined"):
        AgentCoreMemoryStore.from_config({"memory_id": "mem-123"})


def test_from_config_rejects_unknown_actor_id_source() -> None:
    with pytest.raises(ValueError, match="actor_id_source must be one of"):
        AgentCoreMemoryStore.from_config(
            {
                "memory_id": "mem-123",
                "namespaces": {"long_term": "/facts/{actor_id}"},
                "actor_id_source": "tenant_id",
            }
        )


def test_namespaces_accept_yaml_strings_and_lists() -> None:
    store = build_store(
        namespaces={"long_term": ["/facts/{actor_id}", "/preferences/{actor_id}"]}
    )
    assert store.namespaces == {
        MemoryType.LONG_TERM: ("/facts/{actor_id}", "/preferences/{actor_id}")
    }


def test_namespaces_reject_unknown_memory_type() -> None:
    with pytest.raises(ValueError, match="Invalid memory type"):
        build_store(namespaces={"working_set": "/facts/{actor_id}"})


def test_builds_agentcore_store_with_configured_region(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeStore:
        def __init__(self, *, memory_id, **boto3_kwargs):
            captured["memory_id"] = memory_id
            captured.update(boto3_kwargs)

    monkeypatch.setattr(
        "langgraph_checkpoint_aws.AgentCoreMemoryStore", FakeStore, raising=True
    )

    store = AgentCoreMemoryStore.from_config(
        {
            "memory_id": "mem-123",
            "namespaces": {"long_term": "/facts/{actor_id}"},
            "region": "us-west-2",
        }
    )

    assert isinstance(store.store, FakeStore)
    assert captured == {"memory_id": "mem-123", "region_name": "us-west-2"}


def test_falls_back_to_ambient_boto3_region(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeStore:
        def __init__(self, *, memory_id, **boto3_kwargs):
            captured.update(boto3_kwargs)

    monkeypatch.setattr(
        "langgraph_checkpoint_aws.AgentCoreMemoryStore", FakeStore, raising=True
    )
    monkeypatch.setattr(
        "boto3.Session", lambda: SimpleNamespace(region_name="us-east-1")
    )

    AgentCoreMemoryStore(
        memory_id="mem-123", namespaces={"long_term": "/facts/{actor_id}"}
    )

    assert captured == {"region_name": "us-east-1"}


def test_requires_resolvable_region(monkeypatch) -> None:
    monkeypatch.setattr(
        "langgraph_checkpoint_aws.AgentCoreMemoryStore",
        lambda **kwargs: object(),
        raising=True,
    )
    monkeypatch.setattr("boto3.Session", lambda: SimpleNamespace(region_name=None))

    with pytest.raises(ValueError, match="AWS region must be provided"):
        AgentCoreMemoryStore(
            memory_id="mem-123", namespaces={"long_term": "/facts/{actor_id}"}
        )


# ----------------------------------------------------------------------
# Writes
# ----------------------------------------------------------------------


def test_write_memory_creates_event_per_entry_keyed_by_actor_and_session() -> None:
    fake = FakeAgentCoreStore()
    store = build_store(fake=fake)

    store.write_memory(
        [
            MemoryEntry(
                record_id="memory-1",
                session_id="session-1",
                user_id="user-1",
                content="I prefer ASHRAE 90.1-2019",
                metadata={"role": "human"},
            )
        ]
    )

    (op,) = fake.batches[0]
    assert op.namespace == ("user-1", "session-1")
    assert op.key == "memory-1"
    assert isinstance(op.value["message"], HumanMessage)
    assert op.value["message"].content == "I prefer ASHRAE 90.1-2019"


def test_write_memory_batches_entries_in_one_call() -> None:
    fake = FakeAgentCoreStore()
    store = build_store(fake=fake)

    store.write_memory(
        [
            MemoryEntry(
                session_id="s1",
                user_id="user-1",
                content="a",
                metadata={"role": "human"},
            ),
            MemoryEntry(
                session_id="s1",
                user_id="user-1",
                content="b",
                metadata={"role": "agent"},
            ),
        ]
    )

    assert len(fake.batches) == 1
    assert len(fake.batches[0]) == 2


@pytest.mark.parametrize(
    "role,expected_cls",
    [
        ("human", HumanMessage),
        ("agent", AIMessage),
        ("tool", ToolMessage),
        ("system", SystemMessage),
        # No role defaults to HumanMessage (USER turn) so it's retrievable.
        (None, HumanMessage),
    ],
)
def test_write_memory_reconstructs_message_type_from_role(role, expected_cls) -> None:
    fake = FakeAgentCoreStore()
    store = build_store(fake=fake)
    metadata = {"role": role} if role else {}

    store.write_memory(
        [
            MemoryEntry(
                session_id="s1", user_id="user-1", content="hello", metadata=metadata
            )
        ]
    )

    assert isinstance(fake.batches[0][0].value["message"], expected_cls)


@pytest.mark.parametrize("role", ["assistant", "user", "typo", 42, ["human"]])
def test_write_memory_rejects_unsupported_role(role) -> None:
    """An unknown role is rejected to prevent storing under the wrong speaker."""
    fake = FakeAgentCoreStore()
    with pytest.raises(ValueError, match="Unsupported metadata\\['role'\\]"):
        write_entry(build_store(fake=fake), metadata={"role": role})
    assert fake.batches == []


def test_write_memory_preserves_periods_in_actor_id() -> None:
    """batch() with PutOp bypasses the validation that put() enforces."""
    fake = FakeAgentCoreStore()
    write_entry(build_store(fake=fake), user_id="first.last@pnnl.gov")
    assert fake.batches[0][0].namespace == ("first.last@pnnl.gov", "s1")


def test_batch_putop_bypasses_namespace_validation(monkeypatch) -> None:
    """Verify batch() bypasses namespace validation that put() enforces.

    write_memory depends on batch() accepting periods in actor IDs (email addresses).
    If a future langgraph release validates in batch(), this test catches it.
    """
    from langgraph.store.base import InvalidNamespaceError, PutOp
    from langgraph_checkpoint_aws.agentcore.store import (
        AgentCoreMemoryStore as WrapperStore,
    )

    events: list[dict] = []
    monkeypatch.setattr(
        "boto3.client",
        lambda *a, **kw: SimpleNamespace(create_event=lambda **kwargs: events.append(kwargs)),
    )

    wrapper = WrapperStore(memory_id="mem-123", region_name="us-west-2")
    wrapper.batch(
        [
            PutOp(
                ("first.last@pnnl.gov", "s1"),
                "memory-1",
                {"message": HumanMessage("hello")},
            )
        ]
    )

    assert events[0]["actorId"] == "first.last@pnnl.gov"
    # ...and confirm put() is the path that would have rejected it.
    with pytest.raises(InvalidNamespaceError):
        wrapper.put(
            ("first.last@pnnl.gov", "s1"),
            "memory-2",
            {"message": HumanMessage("hello")},
        )


def test_write_memory_rejects_slash_in_identity_values() -> None:
    """Slashes would create unintended namespace segments."""
    store = build_store()

    with pytest.raises(ValueError, match="contains '/'"):
        write_entry(store, user_id="alice/../bob")

    with pytest.raises(ValueError, match="contains '/'"):
        write_entry(store, session_id="s1/preferences", user_id="alice")


@pytest.mark.parametrize("blank", ["   ", "\t"])
def test_write_memory_rejects_blank_identity_values(blank) -> None:
    """Blank values would create empty namespace segments."""
    with pytest.raises(ValueError, match="non-blank string"):
        write_entry(build_store(), user_id=blank)


def test_write_memory_skips_empty_content() -> None:
    fake = FakeAgentCoreStore()
    write_entry(build_store(fake=fake), content="   ")
    assert fake.batches == []


def test_write_memory_ignores_empty_entry_list() -> None:
    fake = FakeAgentCoreStore()
    build_store(fake=fake).write_memory([])
    assert fake.batches == []


def test_write_memory_requires_resolvable_actor_id() -> None:
    with pytest.raises(ValueError, match="no user_id was provided"):
        write_entry(build_store(), user_id=None)


def test_write_memory_uses_session_id_actor_source() -> None:
    fake = FakeAgentCoreStore()
    write_entry(build_store(fake=fake, actor_id_source="session_id"), user_id=None)
    assert fake.batches[0][0].namespace == ("s1", "s1")


def test_rejects_static_actor_id_source() -> None:
    # Removed deliberately: a shared actor would pool every user's conversation
    # turns under one identity. Kept as a test so it is not reintroduced silently.
    with pytest.raises(ValueError, match="actor_id_source must be one of"):
        build_store(actor_id_source="static")


# ----------------------------------------------------------------------
# Reads
# ----------------------------------------------------------------------


def test_read_memories_without_query_returns_empty() -> None:
    fake = FakeAgentCoreStore()
    store = build_store(fake=fake)

    assert store.read_memories(user_id="user-1", memory_type=MemoryType.LONG_TERM) == []
    assert fake.searches == []


def test_read_memories_searches_rendered_namespace() -> None:
    fake = FakeAgentCoreStore(
        results={("preferences", "user-1"): [make_item("rec-1", "prefers 90.1", 0.9)]}
    )
    store = build_store(fake=fake)

    memories = store.read_memories(
        "what code do I use?",
        user_id="user-1",
        session_id="session-1",
        task_id="task-1",
        memory_type=MemoryType.LONG_TERM,
        limit=5,
    )

    assert fake.searches == [
        {
            "namespace": ("preferences", "user-1"),
            "query": "what code do I use?",
            "limit": 5,
        }
    ]
    (memory,) = memories
    assert memory.content == "prefers 90.1"
    assert memory.record_id == "rec-1"
    # Backend doesn't return these fields; not back-filled from query context.
    assert memory.session_id == ""
    assert memory.task_id is None
    assert memory.user_id is None
    assert memory.metadata["agentcore_query_actor_id"] == "user-1"
    assert memory.memory_type is MemoryType.LONG_TERM
    assert memory.metadata["source"] == "agentcore"
    assert memory.metadata["memory_strategy_id"] == "strategy-1"
    assert memory.metadata["relevance_score"] == 0.9


def test_read_memories_orders_by_relevance_without_touching_importance() -> None:
    fake = FakeAgentCoreStore(
        results={
            ("preferences", "user-1"): [
                make_item("rec-low", "low", 0.2),
                make_item("rec-high", "high", 0.95),
                make_item("rec-none", "unscored", None),
            ]
        }
    )
    store = build_store(fake=fake)

    memories = store.read_memories(
        "q", user_id="user-1", memory_type=MemoryType.LONG_TERM
    )

    assert [m.record_id for m in memories] == ["rec-high", "rec-none", "rec-low"]
    # Relevance is query-specific metadata; importance_score stays at default.
    assert [m.importance_score for m in memories] == [0.5, 0.5, 0.5]
    assert [m.metadata.get("relevance_score") for m in memories] == [0.95, None, 0.2]


@pytest.mark.parametrize("bad_score", [float("nan"), float("inf"), "high"])
def test_read_memories_treats_unusable_scores_as_unscored(bad_score) -> None:
    """NaN/inf/non-numeric scores can't be used for ranking."""
    fake = FakeAgentCoreStore(
        results={("preferences", "user-1"): [
            make_item("rec-bad", "bad score", bad_score),
            make_item("rec-good", "good", 0.9),
        ]}
    )
    memories = build_store(fake=fake).read_memories("q", user_id="user-1",
                                                    memory_type=MemoryType.LONG_TERM)

    assert [m.record_id for m in memories] == ["rec-good", "rec-bad"]
    assert "relevance_score" not in memories[1].metadata


def test_read_memories_rejects_unsupported_kwargs() -> None:
    """Unsupported params are rejected before query processing."""
    store = build_store()

    with pytest.raises(NotImplementedError, match="metadata filtering"):
        store.read_memories("q", user_id="user-1", metadata={"tag": "x"})

    with pytest.raises(NotImplementedError, match="tenant_id"):
        store.read_memories(None, user_id="user-1", tenant_id="t1")


@pytest.mark.parametrize("empty", [None, {}])
def test_read_memories_accepts_empty_metadata(empty) -> None:
    """Empty metadata is allowed; only non-empty metadata triggers rejection."""
    fake = FakeAgentCoreStore(
        results={("preferences", "user-1"): [make_item("rec-1", "fact", 0.9)]}
    )
    memories = build_store(fake=fake).read_memories("q", user_id="user-1", metadata=empty)
    assert [m.record_id for m in memories] == ["rec-1"]


def test_read_memories_returns_naive_timestamps_for_manager_ranking() -> None:
    """Timestamps are naive to match DefaultMemoryManager's ranking expectations."""
    created = datetime.now(timezone.utc) - timedelta(hours=2)
    fake = FakeAgentCoreStore(
        results={("preferences", "user-1"): [make_item("rec-1", "fact", 0.5, created)]}
    )
    (memory,) = build_store(fake=fake).read_memories("q", user_id="user-1",
                                                     memory_type=MemoryType.LONG_TERM)
    assert memory.timestamp.tzinfo is None
    assert 0.0 <= DefaultMemoryManager.calculate_recency_score(memory) <= 1.0


def test_read_memories_dedupes_across_namespaces_and_applies_limit() -> None:
    shared = make_item("rec-1", "shared", 0.9)
    fake = FakeAgentCoreStore(
        results={
            ("facts", "user-1"): [shared, make_item("rec-2", "second", 0.8)],
            ("preferences", "user-1"): [shared, make_item("rec-3", "third", 0.7)],
        }
    )
    store = build_store(
        fake=fake,
        namespaces={"long_term": ["/facts/{actor_id}", "/preferences/{actor_id}"]},
    )

    memories = store.read_memories(
        "q", user_id="user-1", memory_type=MemoryType.LONG_TERM, limit=2
    )

    assert len(fake.searches) == 2
    assert [m.record_id for m in memories] == ["rec-1", "rec-2"]


def test_read_memories_returns_empty_for_unconfigured_memory_type() -> None:
    fake = FakeAgentCoreStore()
    store = build_store(fake=fake, namespaces={"long_term": "/facts/{actor_id}"})
    assert store.read_memories("q", user_id="user-1", memory_type=MemoryType.SEMANTIC) == []
    assert fake.searches == []


def test_read_memories_defaults_to_long_term_namespace() -> None:
    fake = FakeAgentCoreStore()
    build_store(fake=fake).read_memories("q", user_id="user-1")
    assert fake.searches[0]["namespace"] == ("preferences", "user-1")


def test_read_memories_skips_namespace_missing_a_placeholder_value() -> None:
    # The episodic template needs a session_id, which this call does not supply.
    fake = FakeAgentCoreStore()
    store = build_store(fake=fake)
    assert store.read_memories("q", user_id="user-1", memory_type=MemoryType.EPISODIC) == []
    assert fake.searches == []


def test_unknown_placeholder_rejected_at_construction() -> None:
    # Invalid placeholders fail fast at construction, not silently at read time.
    with pytest.raises(ValueError, match="Unknown placeholder"):
        build_store(namespaces={"long_term": "/facts/{tenant_id}"})


def test_read_memories_renders_multi_segment_namespace() -> None:
    fake = FakeAgentCoreStore()
    build_store(fake=fake).read_memories(
        "q", user_id="user-1", session_id="session-1", memory_type=MemoryType.EPISODIC)
    assert fake.searches[0]["namespace"] == ("summaries", "user-1", "session-1")


# ----------------------------------------------------------------------
# Unsupported mutations
# ----------------------------------------------------------------------


def test_read_memories_rejects_slash_in_identity_values() -> None:
    store = build_store()

    with pytest.raises(ValueError, match="contains '/'"):
        store.read_memories("q", user_id="alice/../bob")

    # Slashes in any template variable would create unintended segments.
    with pytest.raises(ValueError, match="contains '/'"):
        store.read_memories("q", user_id="alice", session_id="s1/preferences",
                          memory_type=MemoryType.EPISODIC)


def build_wrapper_store(monkeypatch, client) -> AgentCoreMemoryStore:
    """Real langgraph store with stubbed AWS client for testing delete_memory."""
    monkeypatch.setattr("boto3.client", lambda *a, **kw: client)
    from langgraph_checkpoint_aws.agentcore.store import (
        AgentCoreMemoryStore as WrapperStore,
    )

    return AgentCoreMemoryStore(
        memory_id="mem-123",
        namespaces={"long_term": "/preferences/{actor_id}"},
        store=WrapperStore(memory_id="mem-123", region_name="us-west-2"),
    )


def client_error(code: str) -> Exception:
    from botocore.exceptions import ClientError

    return ClientError({"Error": {"Code": code, "Message": code}}, "DeleteMemoryRecord")


def test_delete_memory_deletes_record_by_id(monkeypatch) -> None:
    calls: list[dict] = []
    store = build_wrapper_store(
        monkeypatch,
        SimpleNamespace(delete_memory_record=lambda **kwargs: calls.append(kwargs)),
    )

    assert store.delete_memory("rec-1") is True
    assert calls == [{"memoryId": "mem-123", "memoryRecordId": "rec-1"}]


def test_delete_memory_reports_missing_resource_as_failure(monkeypatch) -> None:
    def raise_not_found(**_kwargs):
        raise client_error("ResourceNotFoundException")

    store = build_wrapper_store(
        monkeypatch, SimpleNamespace(delete_memory_record=raise_not_found)
    )

    assert store.delete_memory("rec-1") is False


def test_delete_memory_propagates_access_denied(monkeypatch) -> None:
    """Permission errors are raised, not masked as "not found"."""

    def raise_denied(**_kwargs):
        raise client_error("AccessDeniedException")

    store = build_wrapper_store(
        monkeypatch, SimpleNamespace(delete_memory_record=raise_denied)
    )

    from botocore.exceptions import ClientError

    with pytest.raises(ClientError):
        store.delete_memory("rec-1")


def test_delete_memory_reports_failure_without_a_client() -> None:
    # Stores without a boto3 client return False instead of pretending to succeed.
    assert build_store().delete_memory("rec-1") is False


def test_clear_memories_raises_rather_than_pretending_to_clear() -> None:
    # AgentCore has no bulk-delete; raise instead of silently doing nothing.
    with pytest.raises(NotImplementedError, match="clear_memories"):
        build_store().clear_memories(MemoryType.LONG_TERM)


# ----------------------------------------------------------------------
# Manager integration
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manager_reads_long_term_memories_from_agentcore() -> None:
    fake = FakeAgentCoreStore(
        results={("preferences", "user-1"): [make_item("rec-1", "prefers 90.1", 0.9)]}
    )
    manager = DefaultMemoryManager(
        long_term_store=build_store(
            fake=fake, namespaces={"long_term": "/preferences/{actor_id}"}
        )
    )

    memories = await manager.retrieve_memories(
        "which code?",
        session_id="session-1",
        user_id="user-1",
        metadata={},  # What MemoryContextProvider forwards from TurnRequest.
        memory_types=[MemoryType.LONG_TERM],
        include_short_term=False,
    )

    assert [m.content for m in memories] == ["prefers 90.1"]


@pytest.mark.asyncio
async def test_manager_without_short_term_store_writes_straight_to_agentcore() -> None:
    """A long-term-only manager must not require a short-term store to write."""
    fake = FakeAgentCoreStore()
    manager = DefaultMemoryManager(long_term_store=build_store(fake=fake))

    await manager.add_memory(
        HumanMessage(content="hello"),
        session_id="session-1",
        user_id="user-1",
        memory_type=MemoryType.SHORT_TERM,
    )
    # Called after every turn by the agent's memory writer; a missing
    # short-term store must be a no-op rather than an AttributeError.
    await manager.manage_memory_size()

    assert len(fake.batches) == 1
    (op,) = fake.batches[0]
    assert op.namespace == ("user-1", "session-1")
