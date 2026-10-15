"""
onnx_embed.py -- all-MiniLM-L6-v2 embeddings via ONNX Runtime (replaces
sentence-transformers, whose PyTorch dependency exceeds Lambda's 250MB limit).
Mean pooling + L2 normalization match sentence-transformers' output.

Model location:
- Local dev: model.onnx next to this file is used if present.
- Lambda: model.onnx is too large for the 250 MB package, so it is downloaded
  once per cold start from s3://$MODEL_S3_BUCKET/$MODEL_S3_KEY into /tmp.
tokenizer.json is always bundled next to this file.
"""
import os
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

_MODEL_DIR = os.path.dirname(os.path.abspath(__file__))
_LOCAL_MODEL_PATH = os.path.join(_MODEL_DIR, "model.onnx")
_TMP_MODEL_PATH = "/tmp/model.onnx"
_TOKENIZER_PATH = os.path.join(_MODEL_DIR, "tokenizer.json")

_session = None
_tokenizer = None


def _resolve_model_path() -> str:
    if os.path.exists(_LOCAL_MODEL_PATH):
        return _LOCAL_MODEL_PATH
    if not os.path.exists(_TMP_MODEL_PATH):
        bucket = os.environ.get("MODEL_S3_BUCKET")
        if not bucket:
            raise RuntimeError("model.onnx is not bundled and MODEL_S3_BUCKET is not set")
        key = os.environ.get("MODEL_S3_KEY", "models/model.onnx")
        import boto3  # provided by the Lambda runtime; only needed on this path
        partial = _TMP_MODEL_PATH + ".part"  # avoids a half-written model if the download dies
        boto3.client("s3").download_file(bucket, key, partial)
        os.replace(partial, _TMP_MODEL_PATH)
    return _TMP_MODEL_PATH


def _get_session():
    global _session
    if _session is None:
        _session = ort.InferenceSession(_resolve_model_path(), providers=["CPUExecutionProvider"])
    return _session


def _get_tokenizer():
    global _tokenizer
    if _tokenizer is None:
        _tokenizer = Tokenizer.from_file(_TOKENIZER_PATH)
        _tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        _tokenizer.enable_truncation(max_length=256)
    return _tokenizer


def _mean_pooling(token_embeddings: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
    mask_expanded = np.expand_dims(attention_mask, -1).astype(np.float32)
    mask_expanded = np.broadcast_to(mask_expanded, token_embeddings.shape)
    summed = np.sum(token_embeddings * mask_expanded, axis=1)
    counts = np.clip(mask_expanded.sum(axis=1), a_min=1e-9, a_max=None)
    return summed / counts


def get_embedding(text: str) -> list[float]:
    tokenizer = _get_tokenizer()
    session = _get_session()

    encoding = tokenizer.encode(text)
    input_ids = np.array([encoding.ids], dtype=np.int64)
    attention_mask = np.array([encoding.attention_mask], dtype=np.int64)
    token_type_ids = np.zeros_like(input_ids)

    outputs = session.run(None, {
        "input_ids": input_ids,
        "attention_mask": attention_mask,
        "token_type_ids": token_type_ids,
    })
    token_embeddings = outputs[0]  # (1, seq_len, 384) last_hidden_state

    sentence_embedding = _mean_pooling(token_embeddings, attention_mask)

    # L2-normalize: required because the OpenSearch index uses innerproduct.
    norm = np.linalg.norm(sentence_embedding, axis=1, keepdims=True)
    sentence_embedding = sentence_embedding / norm

    return sentence_embedding[0].tolist()