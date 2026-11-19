"""Local OCR provider used for stored post media."""

from __future__ import annotations

from pathlib import Path
import threading
from typing import Any


class RapidOCRProvider:
    """Lazy RapidOCR integration so the service can start without downloading models."""

    engine_name = "rapidocr"

    def __init__(self):
        self._engine: Any = None
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        try:
            import rapidocr  # noqa: F401
            import onnxruntime  # noqa: F401
        except ImportError:
            return False
        return True

    @property
    def version(self) -> str:
        try:
            import rapidocr
            return str(getattr(rapidocr, "__version__", ""))
        except ImportError:
            return ""

    def _get_engine(self):
        if self._engine is not None:
            return self._engine
        with self._lock:
            if self._engine is None:
                from rapidocr import RapidOCR
                self._engine = RapidOCR()
        return self._engine

    @staticmethod
    def _lines(result: Any) -> list[str]:
        values = getattr(result, "txts", None)
        if isinstance(values, (list, tuple)):
            return [str(value).strip() for value in values if str(value).strip()]
        if isinstance(result, tuple):
            result = result[0] if result else []
        if not isinstance(result, (list, tuple)):
            return []
        lines = []
        for item in result:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                value = item[1]
                if isinstance(value, (list, tuple)):
                    value = value[0] if value else ""
                value = str(value).strip()
                if value:
                    lines.append(value)
        return lines

    def analyze(self, image_path: str | Path) -> str:
        result = self._get_engine()(str(image_path))
        return "\n".join(self._lines(result))
