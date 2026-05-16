import hashlib
import logging
import os
import threading
from datetime import datetime

log = logging.getLogger("jarvis.memory.semantic")

# Slot keys whose values must never be stored
_SENSITIVE_KEYS = frozenset({"password", "token", "secret"})


def _is_sensitive(metadata: dict) -> bool:
    return any(k in _SENSITIVE_KEYS for k in metadata)


class SemanticMemory:
    """Persistent vector memory backed by ChromaDB + sentence-transformers."""

    def __init__(self, config: dict, llm=None):
        self._llm = llm
        self._lock = threading.Lock()

        persist_dir = config.get(
            "vector_db_path",
            os.path.expanduser("~/.jarvis/chroma"),
        )
        os.makedirs(persist_dir, exist_ok=True)

        try:
            import chromadb
            from chromadb.utils.embedding_functions import (
                SentenceTransformerEmbeddingFunction,
            )

            ef = SentenceTransformerEmbeddingFunction(
                model_name="all-MiniLM-L6-v2"
            )
            self._client = chromadb.PersistentClient(path=persist_dir)
            self._collection = self._client.get_or_create_collection(
                name="jarvis_memory",
                embedding_function=ef,
            )
            log.info(
                "Semantic memory ready (%d facts) — %s",
                self._collection.count(),
                persist_dir,
            )
        except Exception as exc:
            log.error("Failed to initialize semantic memory: %s", exc)
            self._client = None
            self._collection = None

    # ── helpers ──────────────────────────────────────────────────

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _ready(self) -> bool:
        return self._collection is not None

    # ── public API ───────────────────────────────────────────────

    def store_fact(self, text: str, metadata: dict | None = None):
        try:
            if not self._ready():
                return
            metadata = metadata or {}
            if _is_sensitive(metadata):
                log.debug("Skipping sensitive fact.")
                return
            metadata.setdefault("source", "user_fact")
            metadata.setdefault("timestamp", datetime.now().isoformat())

            doc_id = self._hash(text)
            with self._lock:
                existing = self._collection.get(ids=[doc_id])
                if existing and existing["ids"]:
                    log.debug("Duplicate fact skipped: %s…", text[:40])
                    return
                self._collection.add(
                    ids=[doc_id],
                    documents=[text],
                    metadatas=[metadata],
                )
            log.info("Stored fact: %s…", text[:60])
        except Exception as exc:
            log.warning("store_fact failed: %s", exc)

    def query(self, text: str, n_results: int = 5) -> list[dict]:
        try:
            if not self._ready():
                return []
            results = self._collection.query(
                query_texts=[text], n_results=n_results
            )
            out = []
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                out.append({"text": doc, "metadata": meta, "distance": dist})
            return out
        except Exception as exc:
            log.warning("query failed: %s", exc)
            return []

    def delete_by_topic(self, topic: str):
        try:
            if not self._ready():
                return
            results = self._collection.query(
                query_texts=[topic], n_results=10
            )
            ids = results["ids"][0] if results["ids"] else []
            if ids:
                self._collection.delete(ids=ids)
                log.info("Deleted %d facts matching '%s'", len(ids), topic)
        except Exception as exc:
            log.warning("delete_by_topic failed: %s", exc)

    def summarize_and_store_session(self, action_log_rows: list[dict]):
        try:
            if not self._ready():
                return
            if not action_log_rows:
                log.warning("Empty action log — skipping session summary.")
                return
            if not self._llm or not self._llm.enabled:
                log.warning("LLM disabled — skipping session summary.")
                return

            lines = []
            for row in action_log_rows:
                ts = row.get("timestamp", "")
                intent = row.get("intent", "")
                raw = row.get("raw_text", "")
                lines.append(f"[{ts}] {intent}: {raw}")
            log_text = "\n".join(lines)

            prompt = (
                "Summarize the following Jarvis session log in 2-3 concise "
                "sentences. Focus on what the user did and any notable "
                "patterns.\n\n" + log_text
            )
            summary = self._llm.query(prompt)
            if summary:
                self.store_fact(
                    summary,
                    {"source": "session_summary",
                     "timestamp": datetime.now().isoformat()},
                )
        except Exception as exc:
            log.warning("summarize_and_store_session failed: %s", exc)

    def extract_and_store_facts(self, text: str):
        try:
            if not self._ready():
                return
            if not self._llm or not self._llm.enabled:
                return

            prompt = (
                "Does the following user utterance contain a personal fact "
                "worth remembering (schedule, habit, project, preference)? "
                "If yes, reply with ONLY the fact as a short sentence. "
                "If no, reply with exactly 'NONE'.\n\n"
                f"Utterance: {text}"
            )
            result = self._llm.query(prompt)
            if result and result.strip().upper() != "NONE":
                self.store_fact(
                    result.strip(),
                    {"source": "user_fact",
                     "timestamp": datetime.now().isoformat()},
                )
        except Exception as exc:
            log.warning("extract_and_store_facts failed: %s", exc)

    def close(self):
        try:
            if self._client is not None:
                # PersistentClient auto-persists; just drop references
                self._client = None
                self._collection = None
                log.info("Semantic memory closed.")
        except Exception as exc:
            log.warning("semantic memory close failed: %s", exc)
