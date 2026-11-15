import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


@lru_cache(maxsize=1)
def get_embedding_model():
    """Load the configured embedding model only when retrieval needs it."""
    from sentence_transformers import SentenceTransformer

    model_name = os.getenv("EMBEDDING_MODEL")

    if not model_name:
        raise RuntimeError(
            "EMBEDDING_MODEL is not configured. "
            "Set it to the same model used to generate "
            "the embeddings stored in Supabase."
        )

    model = SentenceTransformer(model_name)

    dimensions = model.get_sentence_embedding_dimension()

    if dimensions != 768:
        raise RuntimeError(
            f"Embedding model '{model_name}' produces "
            f"{dimensions} dimensions; expected 768. "
            "Check the model against existing database embeddings."
        )

    return model


def embed_query(text: str):
    """Generate a 768-dimensional query embedding."""
    return get_embedding_model().encode(text).tolist()
