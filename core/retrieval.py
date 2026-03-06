"""
Retrieval index for few-shot example selection.

Embeds your training data (8,034 text-to-SQL pairs) into vectors,
stores them in a FAISS index, and provides fast similarity search.
At query time, finds the most similar past queries to use as few-shot
examples in the Opus prompt.
"""

import numpy as np
import pandas as pd
import faiss
from sentence_transformers import SentenceTransformer
from rich.console import Console

from core.config import Config

console = Console()


class RetrievalIndex:
    def __init__(self, config: Config):
        self.config = config
        self.df: pd.DataFrame = None
        self.index: faiss.IndexFlatIP = None
        self.embedder: SentenceTransformer = None
        self._loaded = False

    # Initialization (called once at startup)

    def load(self):
        """Load CSV, download embedding model, build FAISS index."""
        cfg = self.config.retrieval
        csv_path = cfg["training_data"]

        # Load training pairs
        console.log(f"[bold blue]Loading training data:[/] {csv_path}")
        self.df = pd.read_csv(csv_path)
        self.df = self.df.dropna(subset=["text_query", "sql_command"])
        console.log(f"  → {len(self.df):,} query pairs loaded")

        # Load embedding model
        console.log(f"[bold blue]Loading embedding model:[/] {cfg['embedding_model']}")
        self.embedder = SentenceTransformer(cfg["embedding_model"])

        # Embed all training queries and build index
        console.log("[bold blue]Building FAISS index...[/]")
        embeddings = self.embedder.encode(
            self.df["text_query"].tolist(),
            show_progress_bar=True,
            normalize_embeddings=True,     # Normalize so inner product = cosine similarity
            batch_size=128
        )
        dim = embeddings.shape[1]
        self.index = faiss.IndexFlatIP(dim)  # Inner Product index
        self.index.add(embeddings.astype("float32"))
        console.log(f"  → Index built: {self.index.ntotal} vectors, dim={dim}")
        self._loaded = True

    # Query (called per user request)
    def retrieve(self, query: str, k: int = None) -> list[dict]:
        """
        Find the k most similar training pairs to the given query.

        Returns list of dicts with keys: text_query, sql_command, similarity
        """
        if not self._loaded:
            self.load()

        k = k or self.config.retrieval.get("top_k", 5)
        min_sim = self.config.retrieval.get("min_similarity", 0.0)

        # Embed the new query
        q_emb = self.embedder.encode([query], normalize_embeddings=True)

        # Search the index
        scores, indices = self.index.search(q_emb.astype("float32"), k)

        # Build results, filtering by minimum similarity
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if score < min_sim:
                continue
            results.append({
                "text_query": self.df.iloc[idx]["text_query"],
                "sql_command": self.df.iloc[idx]["sql_command"],
                "similarity": round(float(score), 4)
            })
        return results