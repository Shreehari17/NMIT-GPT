from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv
import os

load_dotenv()

MODEL_NAME = os.getenv("EMBEDDING_MODEL")
model = SentenceTransformer(MODEL_NAME)

def embed_query(text: str):
    """Generate a 768-dim embedding for the incoming query."""
    return model.encode(text).tolist()
