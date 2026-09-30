from pathlib import Path
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_openai import OpenAIEmbeddings
import chromadb
import os


from dotenv import load_dotenv

load_dotenv()
root = Path(r"E:\Forward deployment engineer\Warden\data")

folder_map = {
    "policy_docs": root / "policy-docs",
    "slack_messages": root / "slack-messages",
    "support_tickets": root / "support-tickets",
}


def detect_access_level(content: str) -> str:
    """
    Access level is parsed from a marker already written into each fake
    document's own text - "(Confidential...)", "(Restricted...)" /
    "Manager Access" - rather than a hand-maintained filename list. The
    old access_map only listed 4 policy-doc filenames, so every support
    ticket and every Slack message silently fell through to "public",
    including ones explicitly marked manager-only in their own text.
    Scanning content means every file is classified correctly regardless
    of whether its name was remembered in a list.
    """
    if "(Confidential" in content:
        return "manager"
    if "(Restricted" in content or "Manager Access" in content:
        return "manager"
    return "public"


#Second convert to a vector
splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)

persist_directory = str(root / "chroma_store")

# Reset each collection before repopulating, so re-running this script
# (e.g. after fixing access levels, or after adding new documents) never
# leaves stale, incorrectly-tagged chunks sitting alongside corrected
# ones - Chroma.from_texts() only adds, it doesn't replace.
chroma_client = chromadb.PersistentClient(path=persist_directory)

for collection_name, folder in folder_map.items():

    try:
        chroma_client.delete_collection(collection_name)
    except Exception:
        pass  # didn't exist yet - fine

    all_chunks = []
    all_metadata = []

    for file_path in sorted(folder.glob("*.md")):

        text = file_path.read_text(encoding="utf-8")
        chunks = splitter.split_text(text)

        access_level = detect_access_level(text)

        for chunk in chunks:
            all_chunks.append(chunk)

            all_metadata.append({
                "source": file_path.name,
                "access_level": access_level
            })



    if not all_chunks:
        print(f"No markdown files found in {folder}")
        continue

    vector_db = Chroma.from_texts(
        texts=all_chunks,
        metadatas=all_metadata,
        embedding=OpenAIEmbeddings(model="text-embedding-3-small"),
        collection_name=collection_name,
        persist_directory=persist_directory
    )

    manager_count = sum(1 for m in all_metadata if m["access_level"] == "manager")
    print(f"Stored {len(all_chunks)} chunks in collection: {collection_name} "
          f"({manager_count} manager-only chunks)")
