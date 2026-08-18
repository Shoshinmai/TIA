from dataclasses import dataclass
from typing import Any


@dataclass
class Artifact:

    artifact_id: str

    artifact_type: str

    summary: str

    data: Any

    metadata: dict