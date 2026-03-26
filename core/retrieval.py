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
import os
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
        self.index_file = "training_index.faiss"
        self.embeddings_file = "training_embeddings.npy"

    # ── Initialization ────────────────────────────────────────────

    def load(self):
        """
        Load CSV, embedding model, and FAISS index.

        The CSV and embedder are ALWAYS loaded — they are required by
        retrieve() regardless of whether the FAISS index comes from disk
        or is built fresh. Loading only the FAISS cache without them would
        cause a crash on the second run when retrieve() calls
        self.embedder.encode() and self.df.iloc[idx].

        On first run:  CSV + embedder loaded, index built and saved to disk.
        On later runs: CSV + embedder loaded, index read from disk (fast path).
        """
        cfg = self.config.retrieval

        # Step 1: Always load training data and embedding model —
        # both are needed at query time regardless of index cache status.
        console.log(f"[bold blue]Loading training data:[/] {cfg['training_data']}")
        self.df = pd.read_csv(cfg["training_data"])
        self.df = self.df.dropna(subset=["text_query", "sql_command"])
        console.log(f"  → {len(self.df):,} query pairs loaded")

        console.log(f"[bold blue]Loading embedding model:[/] {cfg['embedding_model']}")
        self.embedder = SentenceTransformer(cfg["embedding_model"])

        # Step 2: Load FAISS index from disk if available, otherwise build it.
        if os.path.exists(self.index_file) and os.path.exists(self.embeddings_file):
            self.index = faiss.read_index(self.index_file)
            console.log(
                f"  → FAISS index loaded from disk "
                f"({self.index.ntotal:,} vectors)"
            )
        else:
            console.log("[bold blue]Building FAISS index...[/]")
            embeddings = self.embedder.encode(
                self.df["text_query"].tolist(),
                show_progress_bar=True,
                normalize_embeddings=True,   # normalize so inner product = cosine similarity
                batch_size=128,
            )
            dim = embeddings.shape[1]
            self.index = faiss.IndexFlatIP(dim)
            self.index.add(embeddings.astype("float32"))
            self._save_index(embeddings)
            console.log(
                f"  → Index built and saved: "
                f"{self.index.ntotal:,} vectors, dim={dim}"
            )

        self._loaded = True

    def _save_index(self, embeddings: np.ndarray):
        """Persist FAISS index and embeddings to disk for faster future startups."""
        faiss.write_index(self.index, self.index_file)
        np.save(self.embeddings_file, embeddings)

    # ── Query ─────────────────────────────────────────────────────

    def retrieve(self, query: str, k: int = None) -> list[dict]:
        """
        Find the k most similar training pairs to the given query.

        Returns list of dicts with keys: text_query, sql_command, similarity.
        """
        if not self._loaded:
            self.load()

        k = k or self.config.retrieval.get("top_k", 5)
        min_sim = self.config.retrieval.get("min_similarity", 0.0)

        # Embed the new query and search the index
        q_emb = self.embedder.encode([query], normalize_embeddings=True)
        scores, indices = self.index.search(q_emb.astype("float32"), k)

        # Build results, filtering by minimum similarity
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if score < min_sim:
                continue
            results.append({
                "text_query":  self.df.iloc[idx]["text_query"],
                "sql_command": self.df.iloc[idx]["sql_command"],
                "similarity":  round(float(score), 4),
            })
        return results