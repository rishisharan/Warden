
from dotenv import load_dotenv

load_dotenv()

from pathlib import Path
from dotenv import load_dotenv
from langchain_community.vectorstores import Chroma
from langchain_openai import OpenAIEmbeddings

load_dotenv()

root = Path(r"E:\Forward deployment engineer\Warden\data")

# 1. Create the SAME embedding model used during ingestion
embeddings = OpenAIEmbeddings(
    model="text-embedding-3-small"
)

# 2. Connect to your EXISTING Chroma collection
vector_db = Chroma(
    collection_name="policy_docs",
    embedding_function=embeddings,
    persist_directory=str(root / "chroma_store")
)

# 3. Search
# query = """
# A $90K ARR customer is thinking about leaving us.
# What discount can I offer them?
# """

query = "What is our guaranteed service uptime?"

results = vector_db.similarity_search_with_score(query, k=3, filter={ "$or": [
        {"access_level": "public"},
        {"access_level": "manager"}
    ]})

for i, (doc, distance) in enumerate(results):
    print(f"\n--- Result {i + 1} ---")
    print(f"Distance: {distance}")
    print(f"Metadata: {doc.metadata}")
    print(doc.page_content)