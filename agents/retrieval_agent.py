"""agents/retrieval_agent.py -- grounded Q&A over the firm's documents in OpenSearch."""
import os
import boto3
from dotenv import load_dotenv
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth
from onnx_embed import get_embedding
from tokenomics_logger import call_claude, sum_usage

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"), override=True)  # no-op on Lambda

INDEX = "documents"
TOP_K = 3
# innerproduct scores = 1 + similarity. Re-probed on AWS: on-topic questions' top hit
# scored 1.43-1.61, unrelated questions 0.98-1.06.
MIN_SCORE = 1.25  # question gate: is the best hit relevant at all?
MAX_GAP = 0.10    # chunk filter: keep only chunks close to the best hit

_client = None


def _get_client() -> OpenSearch:
    global _client
    if _client is None:
        creds = boto3.Session().get_credentials()
        auth = AWS4Auth(creds.access_key, creds.secret_key, "us-east-1", "es",
                        session_token=creds.token)
        _client = OpenSearch(hosts=[{"host": os.environ["OPENSEARCH_ENDPOINT"], "port": 443}],
                             http_auth=auth, use_ssl=True, verify_certs=True,
                             connection_class=RequestsHttpConnection, timeout=10)
    return _client


def search_documents(query: str, k: int = TOP_K) -> list[dict]:
    body = {"size": k, "_source": ["content", "source", "chunk_number"],
            "query": {"knn": {"embedding": {"vector": get_embedding(query), "k": k}}}}
    hits = _get_client().search(index=INDEX, body=body)["hits"]["hits"]
    return [{"source": h["_source"]["source"], "chunk_number": h["_source"]["chunk_number"],
             "score": round(h["_score"], 3), "content": h["_source"]["content"]} for h in hits]


def _history_block(history: list | None) -> str:
    if not history:
        return ""
    turns = "\n".join(f"Q: {h['question']}\nA: {h['answer']}" for h in history)
    return f"Conversation so far:\n{turns}\n\n"


def _result(success, answer, chunks, top_score, calls, reason) -> dict:
    return {
        "success": success, "answer": answer,
        "sources": sorted({c["source"] for c in chunks}),
        "metadata": {"reason": reason, "top_score": top_score, "min_score": MIN_SCORE,
                     "chunks": [{k: c[k] for k in ("source", "chunk_number", "score")} for c in chunks],
                     "token_usage": sum_usage(calls), "calls": calls},
    }


def run_retrieval_agent(question: str, history: list | None = None) -> dict:
    # Follow-ups like "what about high severity?" need the previous question to search well.
    search_text = f"{history[-1]['question']} {question}" if history else question
    try:
        hits = search_documents(search_text)
    except Exception as e:
        return _result(False, f"Document search failed: {e}", [], None, [], "search_error")

    top_score = hits[0]["score"] if hits else None
    relevant = [h for h in hits
                if top_score >= MIN_SCORE and h["score"] >= top_score - MAX_GAP]
    if not relevant:  # no Claude call -> zero cost for off-topic questions
        return _result(False, "No relevant documents were found for this question.",
                       [], top_score, [], "below_threshold")

    context = "\n\n".join(f"[{c['source']}]\n{c['content']}" for c in relevant)
    prompt = (
        f"{_history_block(history)}Answer the question concisely using ONLY the document excerpts below. "
        "Name the source file for each fact you use. If the excerpts do not contain the "
        "answer, say that the documents do not cover it.\n\n"
        f"Excerpts:\n{context}\n\nQuestion: {question}"
    )
    answer, usage = call_claude(prompt, "retrieval_answer", max_tokens=400)
    return _result(True, answer, relevant, top_score, [usage], "OK")
