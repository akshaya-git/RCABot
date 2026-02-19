"""
RAG Package.

Retrieval-Augmented Generation for runbooks and case history:
- RAGRetriever: Search and index documents in OpenSearch
"""

from .retriever import RAGRetriever

__all__ = ["RAGRetriever"]
