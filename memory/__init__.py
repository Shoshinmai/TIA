from .artifact_store import ArtifactStore
from .retriever import ArtifactRetriever


artifact_store = ArtifactStore()

artifact_retriever = ArtifactRetriever(
    artifact_store=artifact_store
)