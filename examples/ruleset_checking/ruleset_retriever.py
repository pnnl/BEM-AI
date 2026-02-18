from dataclasses import dataclass
from typing import Any

from langchain_chroma import Chroma

from automa_ai.retrieval.base import BaseRetriever
from automa_ai.retrieval.config import RetrieverProviderSpec
from automa_ai.retrieval.embedding_factory import resolve_embeddings


@dataclass
class RulesetRetriever(BaseRetriever):
    store: Chroma
    top_k: int = 4
    embeddings: Any | None = None

    def _format_documents(self, docs: list[Any], scores: list[float] | None = None) -> list[dict[str, Any]]:
        formatted: list[dict[str, Any]] = []
        for idx, doc in enumerate(docs):
            entry: dict[str, Any] = {
                "rule_description": doc.page_content,
                "rule_logic": doc.metadata["rule_logic"],
                "mandatory_rule": doc.metadata.get("mandatory_rule", False),
                "applicability_checks": doc.metadata["applicability_checks"],
                "Appendix_G_section": doc.metadata["Appendix_G_section"],
                "rule_id": doc.metadata["rule_id"],
                "evaluation_context": doc.metadata["evaluation_context"],
                "rule_assertion": doc.metadata.get("rule_assertion", ""),
            }
            if scores is not None:
                entry["score"] = scores[idx]
            formatted.append(entry)
        return formatted

    def similarity_search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        k = top_k or self.top_k
        if hasattr(self.store, "similarity_search_with_relevance_scores"):
            results = self.store.similarity_search_with_relevance_scores(query, k=k, **kwargs)
            docs = [doc for doc, _score in results]
            scores = [score for _doc, score in results]
            return self._format_documents(docs, scores)
        if hasattr(self.store, "similarity_search"):
            docs = self.store.similarity_search(query, k=k, **kwargs)
            return self._format_documents(docs)
        if self.embeddings:
            vector = self.embeddings.embed_query(query)
            return self.similarity_search_by_vector(vector, top_k=k, **kwargs)
        raise ValueError("Chroma store does not support text similarity search.")

    def similarity_search_by_vector(
        self,
        vector: list[float],
        *,
        top_k: int | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        k = top_k or self.top_k
        if hasattr(self.store, "similarity_search_by_vector_with_relevance_scores"):
            results = self.store.similarity_search_by_vector_with_relevance_scores(vector, k=k, **kwargs)
            docs = [doc for doc, _score in results]
            scores = [score for _doc, score in results]
            return self._format_documents(docs, scores)
        if hasattr(self.store, "similarity_search_by_vector"):
            docs = self.store.similarity_search_by_vector(vector, k=k, **kwargs)
            return self._format_documents(docs)
        raise ValueError("Chroma store does not support vector similarity search.")


class RulesetRetrieverProvider:
    @classmethod
    def from_config(cls, spec: RetrieverProviderSpec) -> BaseRetriever:
        config = dict(spec.retrieval_provider_config or {})
        db_path = config.pop("db_path", None)
        persist_directory = config.pop("persist_directory", None)
        collection_name = config.pop("collection_name", None) or "helpdesk_qna"
        chroma_kwargs = config.pop("chroma_kwargs", None)

        persist_directory = persist_directory or db_path
        if not persist_directory:
            raise ValueError("Helpdesk retriever requires 'db_path' or 'persist_directory'.")

        embeddings = resolve_embeddings(spec.embedding) if spec.embedding else None
        init_kwargs: dict[str, Any] = {
            "persist_directory": persist_directory,
            "collection_name": collection_name,
            "embedding_function": embeddings,
        }
        if chroma_kwargs:
            init_kwargs.update(chroma_kwargs)
        if config:
            init_kwargs.update(config)

        store = Chroma(**init_kwargs)
        return RulesetRetriever(store=store, top_k=spec.top_k, embeddings=embeddings)
