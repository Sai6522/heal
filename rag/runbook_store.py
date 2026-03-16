"""
RAG pipeline: ingest SAP runbooks (YAML/MD) into ChromaDB,
then retrieve relevant remediation steps for a given error.
"""
import os, glob, yaml
from pathlib import Path
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import SentenceTransformerEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.schema import Document

# Suppress chromadb telemetry errors
import chromadb.telemetry.product.posthog as _tel
_tel.Posthog.capture = lambda *a, **kw: None

CHROMA_PATH = os.getenv("CHROMA_DB_PATH", "./data/chroma")
RUNBOOKS_DIR = Path(__file__).parent.parent / "runbooks"

embeddings = SentenceTransformerEmbeddings(model_name="all-MiniLM-L6-v2")


def _load_runbooks() -> list[Document]:
    docs = []
    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)

    for path in glob.glob(str(RUNBOOKS_DIR / "**/*"), recursive=True):
        p = Path(path)
        if p.suffix in (".yaml", ".yml"):
            data = yaml.safe_load(p.read_text())
            text = yaml.dump(data)
            meta = {"source": str(p), "error_code": data.get("error_code", "unknown")}
            docs += splitter.create_documents([text], metadatas=[meta])
        elif p.suffix in (".md", ".txt"):
            docs += splitter.create_documents([p.read_text()], metadatas=[{"source": str(p)}])
    return docs


def build_store() -> Chroma:
    docs = _load_runbooks()
    if not docs:
        raise ValueError(f"No runbooks found in {RUNBOOKS_DIR}")
    store = Chroma.from_documents(docs, embeddings, persist_directory=CHROMA_PATH)
    store.persist()
    print(f"[RAG] Indexed {len(docs)} chunks")
    return store


def get_store() -> Chroma:
    if Path(CHROMA_PATH).exists():
        return Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)
    return build_store()


def retrieve(query: str, k: int = 5) -> list[Document]:
    return get_store().similarity_search(query, k=k)
