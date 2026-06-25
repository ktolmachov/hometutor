from app.config import Settings


def test_embedding_defaults_are_local_first() -> None:
    assert Settings.model_fields["embed_api_base"].default == "http://127.0.0.1:1234/v1"
    assert Settings.model_fields["embed_model"].default == "text-embedding-qwen3-embedding-0.6b"
