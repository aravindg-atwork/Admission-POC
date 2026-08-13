"""RAG package - retrieval + prompt assembly + generation orchestration for
admission Q&A. Re-exports the two entry points every external caller
(server.py, prospectus_watch.py) actually uses, so `from . import rag` +
`rag.answer(...)`/`rag.ingest(...)` call sites elsewhere in the codebase
need zero changes after the 2026-08-13 split of the old flat rag.py into
this package (answer.py, guards.py, helpers.py, comparison.py,
orchestrator.py, validate.py, ingest.py).
"""

from .answer import answer
from .ingest import ingest

__all__ = ["answer", "ingest"]
