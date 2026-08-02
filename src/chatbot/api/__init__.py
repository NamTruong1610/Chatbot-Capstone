"""HTTP serving layer (FR-API): a minimal FastAPI app exposing the chat pipeline.

Imports everything below it (docs/04 §6). The app owns no retrieve→generate logic of its own —
it builds one ``ChatPipeline`` at startup (via the shared ``chatbot.pipeline.build_chat_pipeline``)
and each request just calls it, so the endpoint and the evaluation share exactly one compose.
"""

from __future__ import annotations

from chatbot.api.main import create_app

__all__ = ["create_app"]
