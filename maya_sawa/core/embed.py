from typing import List
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Chroma
from langchain.schema import Document
import os

class VectorStore:
    def __init__(self, persist_directory: str = "data/chroma"):
        self.embeddings = OpenAIEmbeddings()
        self.persist_directory = persist_directory
        os.makedirs(persist_directory, exist_ok=True)
        self.db = Chroma(
            persist_directory=persist_directory,
            embedding_function=self.embeddings
        )

    def add_documents(self, documents: List[Document]) -> None:
        """添加文件到向量存儲"""
        self.db.add_documents(documents)
        self.db.persist()

    def similarity_search(self, query: str, k: int = 4) -> List[Document]:
        """搜尋相似文件"""
        return self.db.similarity_search(query, k=k)

    def clear(self) -> None:
        """清除所有向量存儲"""
        self.db.delete_collection()
        self.db = Chroma(
            persist_directory=self.persist_directory,
            embedding_function=self.embeddings
        ) 