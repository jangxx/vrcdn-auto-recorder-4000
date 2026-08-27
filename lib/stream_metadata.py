from dataclasses import dataclass
from datetime import datetime


@dataclass
class StreamMetadata:
    username: str
    startedAt: datetime

    additionalData: dict
