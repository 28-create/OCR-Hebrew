"""Source captures and immutable initial readings are separate from user edits."""
from dataclasses import dataclass, field
import time


@dataclass(frozen=True)
class RawReading:
    text: str
    model: str
    confidence: float


@dataclass
class CaptureRecord:
    image: object
    source: str
    page: int = 0
    document: object = None
    created: float = field(default_factory=time.time)
    reading: RawReading | None = None
    edited_text: str = ''
    timings: dict = field(default_factory=dict)

    @property
    def raw_text(self):
        return self.reading.text if self.reading else ''
