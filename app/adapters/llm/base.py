from typing import Protocol


class LLMAdapter(Protocol):
    def extract(self, document_type: str, blocks: list[dict]) -> dict: ...
