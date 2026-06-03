from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quantagent.embedding_provider import (
    EmbeddingCache,
    EmbeddingJob,
    LocalHashEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
    SentenceTransformersEmbeddingProvider,
    embed_batch,
    embedding_cache_path,
    incremental_embedding_batch,
    render_embedding_status,
    text_sha256,
)


class EmbeddingProviderTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent embeddings ")

    def test_local_batch_embeds_and_persists_cache(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            provider = LocalHashEmbeddingProvider(dimensions=12)
            jobs = [
                EmbeddingJob("a", "portfolio risk capacity"),
                EmbeddingJob("b", "execution slippage model"),
            ]

            batch = embed_batch(project, provider, jobs)
            rendered = render_embedding_status(batch)

            self.assertEqual(batch.provider, "local-hash")
            self.assertEqual(len(batch.records), 2)
            self.assertEqual(batch.cache_hits, 0)
            self.assertEqual(batch.cache_misses, 2)
            self.assertTrue(all(len(record.vector) == 12 for record in batch.records))
            self.assertTrue(embedding_cache_path(project).exists())
            self.assertIn("cache_misses: 2", rendered)

    def test_cache_hit_reuses_vector(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            provider = LocalHashEmbeddingProvider(dimensions=8)
            job = EmbeddingJob("risk", "same risk text")

            first = embed_batch(project, provider, [job])
            second = embed_batch(project, provider, [EmbeddingJob("risk-again", "same risk text")])

            self.assertEqual(first.records[0].vector, second.records[0].vector)
            self.assertEqual(second.cache_hits, 1)
            self.assertEqual(second.cache_misses, 0)
            self.assertTrue(second.records[0].from_cache)
            self.assertEqual(len(EmbeddingCache(project)), 1)

    def test_incremental_skip_unchanged_texts(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            provider = LocalHashEmbeddingProvider(dimensions=8)
            old = "unchanged alpha"
            changed = "changed beta"

            batch = incremental_embedding_batch(project, provider, [old, changed], previous_text_shas=[text_sha256(old)])

            self.assertEqual([record.metadata["index"] for record in batch.records], [1])
            self.assertEqual(batch.records[0].text_sha256, text_sha256(changed))
            self.assertEqual(batch.cache_misses, 1)

    def test_openai_provider_without_key_is_unavailable(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "", "QUANTAGENT_OPENAI_API_KEY": ""}, clear=False):
            provider = OpenAICompatibleEmbeddingProvider(api_key="")
            status = provider.status()
            rendered_json = render_embedding_status(status, fmt="json")

            self.assertFalse(status.available)
            self.assertIn("API_KEY", status.reason)
            self.assertIn('"available": false', rendered_json)

    def test_sentence_transformers_missing_dependency_is_unavailable(self) -> None:
        with patch("importlib.util.find_spec", return_value=None):
            provider = SentenceTransformersEmbeddingProvider()
            status = provider.status()

            self.assertFalse(status.available)
            self.assertIn("not installed", status.reason)


if __name__ == "__main__":
    unittest.main()
