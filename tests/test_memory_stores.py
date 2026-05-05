from types import SimpleNamespace

from automa_ai.memory.chroma_memory_store import ChromaVectorMemoryStore
from automa_ai.memory.memory_types import MemoryEntry, MemoryType
from automa_ai.memory.sqlite_memory_store import SQLiteMemoryStore


class FakeVectorStore:
    def __init__(self) -> None:
        self.texts: list[str] = []
        self.metadatas: list[dict] = []
        self.ids: list[str] = []
        self.deleted_ids: list[str] = []

    def add_texts(self, *, texts, metadatas, ids) -> None:
        self.texts.extend(texts)
        self.metadatas.extend(metadatas)
        self.ids.extend(ids)

    def similarity_search_with_score(self, *, query, k, filter=None):
        return [
            (SimpleNamespace(metadata=metadata), 0.1) for metadata in self.metadatas
        ]

    def delete(self, ids) -> None:
        self.deleted_ids.extend(ids)


def test_chroma_write_records_memory_id() -> None:
    vectorstore = FakeVectorStore()
    store = ChromaVectorMemoryStore.__new__(ChromaVectorMemoryStore)
    store.vectorstore = vectorstore
    store.memory_mapping = {}

    entry = MemoryEntry(
        record_id="memory-1",
        session_id="session-1",
        task_id="task-1",
        user_id="user-1",
        content="remember me",
        memory_type=MemoryType.SHORT_TERM,
    )

    store.write_memory([entry])

    assert vectorstore.metadatas[0]["memory_id"] == "memory-1"
    assert store.read_memories(query="remember", session_id="session-1") == [entry]


def test_sqlite_filters_and_deletes_by_database_id(tmp_path) -> None:
    store = SQLiteMemoryStore(str(tmp_path / "memory.sqlite"))
    matching = MemoryEntry(
        record_id="memory-1",
        session_id="session-1",
        task_id="task-1",
        user_id="user-1",
        content="matching memory",
        memory_type=MemoryType.SHORT_TERM,
    )
    other_user = MemoryEntry(
        record_id="memory-2",
        session_id="session-1",
        task_id="task-1",
        user_id="user-2",
        content="other memory",
        memory_type=MemoryType.SHORT_TERM,
    )

    store.write_memory([matching, other_user])

    memories = store.read_memories(
        session_id="session-1",
        user_id="user-1",
        limit=10,
    )

    assert [memory.content for memory in memories] == ["matching memory"]
    assert memories[0].id is not None
    assert store.delete_memory(str(memories[0].id)) is True
    remaining = store.read_memories(session_id="session-1", limit=10)
    assert [memory.content for memory in remaining] == ["other memory"]
