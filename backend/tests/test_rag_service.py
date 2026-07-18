import unittest

from app.services.rag_service import get_embedding_model


class RagServiceFallbackTest(unittest.TestCase):
    def test_fallback_embedding_model_returns_vectors(self):
        model = get_embedding_model()
        embeddings = model.encode(["bonjour ce document pdf", "upload fonctionne"])

        self.assertEqual(len(embeddings), 2)
        self.assertGreater(len(embeddings[0]), 0)
        self.assertGreater(len(embeddings[1]), 0)


if __name__ == "__main__":
    unittest.main()
