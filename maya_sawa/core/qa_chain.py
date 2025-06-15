from typing import List, Dict
from langchain_openai import ChatOpenAI
from langchain.chains import RetrievalQAWithSourcesChain
from langchain.prompts import PromptTemplate
from langchain.schema import Document

class QAChain:
    def __init__(self):
        self.llm = ChatOpenAI(temperature=0)
        self.chain = None

    def _create_chain(self, retriever):
        """創建問答鏈"""
        template = """使用以下上下文來回答問題。如果你不知道答案，就說你不知道，不要試圖編造答案。

上下文:
{context}

問題: {question}

請用中文回答，並列出參考來源。"""

        PROMPT = PromptTemplate(
            template=template,
            input_variables=["context", "question"]
        )

        self.chain = RetrievalQAWithSourcesChain.from_chain_type(
            llm=self.llm,
            chain_type="stuff",
            retriever=retriever,
            return_source_documents=True,
            chain_type_kwargs={"prompt": PROMPT}
        )

    def get_answer(self, query: str, documents: List[Document]) -> Dict:
        """獲取問題答案"""
        if not self.chain:
            from langchain.schema.retriever import BaseRetriever
            class SimpleRetriever(BaseRetriever):
                def __init__(self, docs):
                    self.docs = docs
                def get_relevant_documents(self, query):
                    return self.docs
            retriever = SimpleRetriever(documents)
            self._create_chain(retriever)

        result = self.chain({"question": query})
        return {
            "answer": result["answer"],
            "sources": [doc.metadata.get("source", "Unknown") for doc in result["source_documents"]]
        } 