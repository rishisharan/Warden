"""
Warden retrieval service - queries (and, since the /ingest endpoint below,
also adds to) the Chroma collections built by data/ground/ingestion.py.

Matches ingestion.py exactly: same embedding model (OpenAI
text-embedding-3-small - must match, different embedding models are not
comparable in the same space), same persist_directory, same three
collections (policy_docs, slack_messages, support_tickets), same
access_level metadata values ("public" / "manager"), same chunking
(RecursiveCharacterTextSplitter, chunk_size=800, chunk_overlap=100).

/search embeds a question, queries all three collections with a metadata
filter restricted to the caller's allowed access levels, merges and
re-sorts by distance, and returns only chunks that filter already
permitted - before anything is returned, not after.

/ingest lets the Warden UI add a single document straight into Chroma at
upload time, tagged with whatever access level the uploader picked in the
UI (public/manager). It is additive (vector_store.add_texts) - unlike
ingestion.py's full re-ingest, a single upload never deletes/resets a
collection, it only appends to it.
"""
import os
from pathlib import Path
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from langchain_community.vectorstores import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

import re
from collections import defaultdict
from rank_bm25 import BM25Okapi

# Same .env ingestion.py reads (OPENAI_API_KEY), so this service doesn't
# need its own copy of the key.
GROUND_DIR = Path(r"E:\Forward deployment engineer\Warden\data\ingestion-pipeline")
load_dotenv(dotenv_path=GROUND_DIR / ".env", override=True)

ROOT = Path(r"E:\Forward deployment engineer\Warden\data")
PERSIST_DIR = str(ROOT / "chroma_store")
COLLECTION_NAMES = ["policy_docs", "slack_messages", "support_tickets"]

# Documents uploaded through the UI join this collection. All three
# collections are searched together in /search regardless, so this only
# affects how uploads are organized/labeled - chosen to reuse the existing
# "knowledge base" collection rather than introduce a fourth one.
UPLOAD_COLLECTION = "policy_docs"
ALLOWED_ACCESS_LEVELS = {"public", "manager"}

embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

vector_stores = {
    name: Chroma(
        collection_name=name,
        embedding_function=embeddings,
        persist_directory=PERSIST_DIR,
    )
    for name in COLLECTION_NAMES
}

# Same settings as data/ground/ingestion.py, so a chunk uploaded through the
# UI looks the same size/shape as one produced by the batch script.
splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)

app = Flask(__name__)


def tokenize(text):
    """Simple tokenization for BM25."""
    return re.findall(r"\b\w+\b", text.lower())


def reciprocal_rank_fusion(dense_results, bm25_results, k=60):
    """Combine two ranked result lists using RRF."""
    scores = defaultdict(float)
    documents = {}

    for results in [dense_results, bm25_results]:
        for rank, item in enumerate(results, start=1):
            doc_id = item["id"]
            scores[doc_id] += 1.0 / (k + rank)
            documents[doc_id] = item

    ranked_ids = sorted(
        scores,
        key=lambda doc_id: scores[doc_id],
        reverse=True
    )

    return [
        {**documents[doc_id], "rrfScore": scores[doc_id]}
        for doc_id in ranked_ids
    ]


@app.post("/search")
def search():
    body = request.get_json(force=True)
    question = body["question"]
    allowed_levels = body.get("allowedAccessLevels", [])
    top_k = max(1, min(int(body.get("topK", 5)), 50))

    # IMPORTANT:
    # Only a trusted, authenticated service should supply
    # allowedAccessLevels. Do not expose this endpoint publicly.
    allowed_levels = [
        level for level in allowed_levels
        if level in ("public", "manager")
    ]

    if not allowed_levels:
        return jsonify({"results": []})

    if len(allowed_levels) == 1:
        access_filter = {
            "access_level": allowed_levels[0]
        }
    else:
        access_filter = {
            "$or": [
                {"access_level": level}
                for level in allowed_levels
            ]
        }

    print("Allowed levels:", allowed_levels)
    print("Chroma filter:", access_filter)

    # Fetch more candidates than we ultimately return.
    candidate_k = max(30, top_k * 5)

    dense_results = []
    bm25_documents = []

    for source_type, store in vector_stores.items():

        # -----------------------------------------
        # 1. DENSE RETRIEVAL (existing Chroma search)
        # -----------------------------------------
        hits = store.similarity_search_with_score(
            question,
            k=candidate_k,
            filter=access_filter
        )

        for doc, distance in hits:
            # Chroma's document ID is preferable to a
            # source filename because files can have
            # multiple chunks.
            content = doc.page_content
            source_file = doc.metadata.get("source")

            doc_id = f"{source_type}::{source_file}::{content}"

            dense_results.append({
                "id": doc_id,
                "sourceFile": source_file,
                "sourceType": source_type,
                "accessLevel": doc.metadata.get("access_level"),
                "content": content,
                "distance": float(distance)
            })

        # -----------------------------------------
        # 2. LOAD AUTHORIZED CHUNKS FOR BM25
        # -----------------------------------------
        collection_data = store._collection.get(
            where=access_filter,
            include=["documents", "metadatas"]
        )

        for content, metadata in zip(
            collection_data["documents"],
            collection_data["metadatas"]
        ):
            source_file = metadata.get("source")

            bm25_documents.append({
                "id": f"{source_type}::{source_file}::{content}",
                "sourceFile": source_file,
                "sourceType": source_type,
                "accessLevel": metadata.get("access_level"),
                "content": content,
                "distance": None
            })

    # -----------------------------------------
    # 3. RANK DENSE RESULTS
    # -----------------------------------------
    dense_results.sort(
        key=lambda item: item["distance"]
    )
    dense_results = dense_results[:candidate_k]

    # -----------------------------------------
    # 4. BM25 KEYWORD RETRIEVAL
    # -----------------------------------------
    bm25_results = []

    if bm25_documents:
        tokenized_corpus = [
            tokenize(item["content"])
            for item in bm25_documents
        ]

        bm25 = BM25Okapi(tokenized_corpus)

        query_tokens = tokenize(question)
        bm25_scores = bm25.get_scores(query_tokens)

        ranked_indices = sorted(
            range(len(bm25_documents)),
            key=lambda i: bm25_scores[i],
            reverse=True
        )

        bm25_results = [
            bm25_documents[i]
            for i in ranked_indices
            if bm25_scores[i] > 0
        ][:candidate_k]

    # -----------------------------------------
    # 5. RECIPROCAL RANK FUSION
    # -----------------------------------------
    combined = reciprocal_rank_fusion(
        dense_results,
        bm25_results,
        k=60
    )

    # -----------------------------------------
    # 6. RETURN TOP K
    # -----------------------------------------
    results = []

    for item in combined[:top_k]:
        
        results.append({
            "id": item["id"],
            "sourceFile": item["sourceFile"],
            "sourceType": item["sourceType"],
            "accessLevel": item["accessLevel"],
            "content": item["content"],
            "distance": item["distance"],
            "rrfScore": item["rrfScore"]
        })

    print("Dense candidates:", len(dense_results))
    print("BM25 candidates:", len(bm25_results))
    print("Hybrid results:", [
        r["sourceFile"] for r in results
    ])

    return jsonify({"results": results})


@app.post("/ingest")
def ingest():
    body = request.get_json(force=True)
    filename = (body.get("filename") or "").strip()
    content = body.get("content") or ""
    access_level = (body.get("accessLevel") or "").strip().lower()

    if not filename:
        return jsonify({"error": "filename is required"}), 400
    if not content.strip():
        return jsonify({"error": "content is empty"}), 400
    if access_level not in ALLOWED_ACCESS_LEVELS:
        return jsonify({"error": f"accessLevel must be one of {sorted(ALLOWED_ACCESS_LEVELS)}"}), 400

    chunks = splitter.split_text(content)
    if not chunks:
        return jsonify({"error": "document produced no chunks"}), 400

    metadatas = [{"source": filename, "access_level": access_level} for _ in chunks]

    # Additive - add_texts appends to the existing collection, it does not
    # wipe it the way ingestion.py's delete_collection()+from_texts() reset
    # does. That reset is right for a full re-ingest of the seed dataset;
    # a single upload from the UI should never nuke everything already in
    # policy_docs.
    vector_stores[UPLOAD_COLLECTION].add_texts(texts=chunks, metadatas=metadatas)

    print(f"Ingested '{filename}' ({access_level}) -> {UPLOAD_COLLECTION}: {len(chunks)} chunks")

    return jsonify({
        "filename": filename,
        "collection": UPLOAD_COLLECTION,
        "accessLevel": access_level,
        "chunksStored": len(chunks),
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8011)))
