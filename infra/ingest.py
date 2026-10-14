"""Chunk -> embed (ONNX) -> index every docs/*.txt into OpenSearch."""
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import boto3
from dotenv import load_dotenv
from opensearchpy import OpenSearch, RequestsHttpConnection, helpers
from requests_aws4auth import AWS4Auth
from onnx_embed import get_embedding

load_dotenv(os.path.join(ROOT, ".env"), override=True)

INDEX = "documents"
CHUNK_SIZE = 120  # words (~160 tokens, under onnx_embed's 256-token truncation)
OVERLAP = 20      # words, so boundary sentences survive intact in one chunk

INDEX_BODY = {
    "settings": {"index.knn": True},
    "mappings": {"properties": {
        "content": {"type": "text"},
        "source": {"type": "keyword"},
        "chunk_number": {"type": "integer"},
        "embedding": {
            "type": "knn_vector", "dimension": 384,
            "method": {"name": "hnsw", "space_type": "innerproduct", "engine": "faiss"},
        },
    }},
}


def get_client() -> OpenSearch:
    creds = boto3.Session().get_credentials()
    auth = AWS4Auth(creds.access_key, creds.secret_key, "us-east-1", "es",
                    session_token=creds.token)
    return OpenSearch(
        hosts=[{"host": os.environ["OPENSEARCH_ENDPOINT"], "port": 443}],
        http_auth=auth, use_ssl=True, verify_certs=True,
        connection_class=RequestsHttpConnection,
    )


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = OVERLAP) -> list[str]:
    words = text.split()
    step = chunk_size - overlap
    return [" ".join(words[i:i + chunk_size])
            for i in range(0, max(len(words) - overlap, 1), step)]


def index_document(client: OpenSearch, path: str) -> int:
    source = os.path.basename(path)
    with open(path, encoding="utf-8") as f:
        chunks = chunk_text(f.read())
    actions = [{
        "_index": INDEX, "_id": f"{source}-{i}",
        "_source": {"content": c, "source": source, "chunk_number": i,
                    "embedding": get_embedding(c)},
    } for i, c in enumerate(chunks)]
    helpers.bulk(client, actions)
    print(f"Indexed {len(chunks)} chunk(s) from {source}")
    return len(chunks)


def main() -> None:
    client = get_client()
    if client.indices.exists(index=INDEX):
        client.indices.delete(index=INDEX)
    client.indices.create(index=INDEX, body=INDEX_BODY)
    for path in sorted(glob.glob(os.path.join(ROOT, "docs", "*.txt"))):
        index_document(client, path)
    client.indices.refresh(index=INDEX)
    print(client.count(index=INDEX))


if __name__ == "__main__":
    main()
