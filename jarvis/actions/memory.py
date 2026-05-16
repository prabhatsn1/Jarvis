import logging
from datetime import datetime

log = logging.getLogger("jarvis.actions.memory")

# Set by core.py at startup when semantic memory is enabled
_semantic_memory = None


def set_semantic_memory(sm):
    global _semantic_memory
    _semantic_memory = sm


def recall_topic(topic: str) -> str:
    if _semantic_memory is None:
        return "Semantic memory is not enabled."
    results = _semantic_memory.query(topic, n_results=3)
    if not results:
        return f"I don't have anything stored about {topic}."
    summaries = [r["text"] for r in results]
    return "Here's what I remember: " + " ".join(summaries)


def store_user_fact(fact: str) -> str:
    if _semantic_memory is None:
        return "Semantic memory is not enabled."
    _semantic_memory.store_fact(
        fact,
        {"source": "user_fact", "timestamp": datetime.now().isoformat()},
    )
    return "Got it, I'll remember that."


def forget_topic(topic: str) -> str:
    if _semantic_memory is None:
        return "Semantic memory is not enabled."
    _semantic_memory.delete_by_topic(topic)
    return f"I've forgotten what I knew about {topic}."
