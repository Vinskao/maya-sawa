from typing import List
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma
from langchain.schema import Document
import os
import logging

logger = logging.getLogger(__name__)

class VectorStore:
    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        api_base = os.getenv("OPENAI_API_BASE")
        logger.debug(f"VectorStore - Using API Base: {api_base}")
        
        self.embeddings = OpenAIEmbeddings(
            openai_organization="org-Fn0OFYXnMJGYRxvbjTbyZX6T",
            base_url=api_base,
            api_key=api_key
        )
        self.vector_store = Chroma(
            persist_directory="data/chroma",
            embedding_function=self.embeddings
        )

    def add_documents(self, documents: List[Document]) -> None:
        """添加文件到向量存儲"""
        self.vector_store.add_documents(documents)
        self.vector_store.persist()

    def similarity_search(self, query: str, k: int = 4) -> List[Document]:
        """搜尋相似文件"""
        return self.vector_store.similarity_search(query, k=k)

    def clear(self) -> None:
        """清除所有向量存儲"""
        self.vector_store.delete_collection()
        self.vector_store = Chroma(
            persist_directory="data/chroma",
            embedding_function=self.embeddings
        ) 