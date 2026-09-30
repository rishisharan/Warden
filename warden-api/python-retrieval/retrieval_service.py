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

# Same .env ingestion.py reads (OPENAI_API_KEY), so this service doesn't
# need its own copy of the key.
GROUND_DIR = Path(r"E:\Forward deployment engineer\Warden\data\ground")
load_dotenv(dotenv_path=GROUND_DIR / ".env")

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


@app.post("/search")
def search():
    body = request.get_json(force=True)
    question = body["question"]
    allowed_levels = body.get("allowedAccessLevels", [])
    top_k = body.get("topK", 5)

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

    combined = []
    for source_type, store in vector_stores.items():
        hits = store.similarity_search_with_score(
            question,
            k=top_k,
            filter=access_filter,
        )
        for i, (doc, distance) in enumerate(hits):
            combined.append({
                "id": f"{source_type}::{doc.metadata.get('source')}::{i}",
                "sourceFile": doc.metadata.get("source"),
                "sourceType": source_type,
                "accessLevel": doc.metadata.get("access_level"),
                "content": doc.page_content,
                "distance": distance,
            })

    # lower distance = more similar; merge across collections then trim
    combined.sort(key=lambda r: r["distance"])
    return jsonify({"results": combined[:top_k]})


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
