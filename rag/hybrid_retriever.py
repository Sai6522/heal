"""
Hybrid retrieval: semantic (ChromaDB) + keyword (BM25) with score fusion.
Gives the LLM the most relevant runbook chunks → higher confidence scores.
"""
import os
from pathlib import Path
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import SentenceTransformerEmbeddings
from langchain_community.retrievers import BM25Retriever
from langchain.retrievers import EnsembleRetriever
from langchain.schema import Document
from rag.runbook_store import _load_runbooks, CHROMA_PATH

embeddings = SentenceTransformerEmbeddings(model_name="all-MiniLM-L6-v2")

_ensemble: EnsembleRetriever | None = None


def get_hybrid_retriever(k: int = 6) -> EnsembleRetriever:
    global _ensemble
    if _ensemble:
        return _ensemble

    docs = _load_runbooks()
    if not docs:
        raise ValueError("No runbooks loaded — run: python main.py index")

    # Semantic retriever
    chroma = Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)
    semantic = chroma.as_retriever(search_kwargs={"k": k})

    # Keyword (BM25) retriever
    bm25 = BM25Retriever.from_documents(docs)
    bm25.k = k

    # 50/50 fusion — tune weights if semantic or keyword dominates
    _ensemble = EnsembleRetriever(
        retrievers=[semantic, bm25],
        weights=[0.5, 0.5],
    )
    return _ensemble


def retrieve_hybrid(query: str, k: int = 6) -> list[Document]:
    return get_hybrid_retriever(k).invoke(query)
