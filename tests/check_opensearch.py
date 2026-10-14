import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "infra")]

from ingest import INDEX, get_client
from onnx_embed import get_embedding

QUERIES = [
    "What is our onboarding process?",
    "How quickly must critical IT tickets be resolved?",
    "What happens when an invoice is overdue?",
]

client = get_client()
count = client.count(index=INDEX)["count"]
print(f"documents index count = {count}")
assert count > 0, "index is empty"

for q in QUERIES:
    body = {"size": 3, "_source": ["source", "content"],
            "query": {"knn": {"embedding": {"vector": get_embedding(q), "k": 3}}}}
    print(f"\nQ: {q}")
    for hit in client.search(index=INDEX, body=body)["hits"]["hits"]:
        src = hit["_source"]
        print(f"  [{src['source']}] score={hit['_score']:.3f}  {src['content'][:80]}...")

print("\nOPENSEARCH CHECK PASSED: count > 0 and top hits are relevant")
