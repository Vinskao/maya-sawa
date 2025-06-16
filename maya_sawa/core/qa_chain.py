from typing import List, Dict
from langchain_openai import ChatOpenAI
from langchain.chains import RetrievalQAWithSourcesChain
from langchain.prompts import PromptTemplate, ChatPromptTemplate
from langchain.schema import Document
from langchain.schema.runnable import RunnablePassthrough
from langchain.schema.output_parser import StrOutputParser
import os
import logging

logger = logging.getLogger(__name__)

class QAChain:
    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        api_base = os.getenv("OPENAI_API_BASE")
        logger.debug(f"QAChain - Using API Base: {api_base}")
        
        self.llm = ChatOpenAI(
            model="gpt-3.5-turbo",
            temperature=0,
            openai_organization="org-Fn0OFYXnMJGYRxvbjTbyZX6T",
            base_url=api_base,
            api_key=api_key
        )
        
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", """你是一個專業的助手，負責回答關於上傳文件的問題。
            請根據提供的文件內容來回答問題。如果問題與文件內容無關，請禮貌地說明。
            回答時請：
            1. 保持專業和準確
            2. 使用清晰的語言
            3. 如果可能，提供具體的例子或引用
            4. 如果不確定，請誠實說明"""),
            ("human", "文件內容：\n{context}\n\n問題：{question}")
        ])
        
        self.chain = (
            {"context": RunnablePassthrough(), "question": RunnablePassthrough()}
            | self.prompt
            | self.llm
            | StrOutputParser()
        )

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

        # Convert documents to context string
        context = "\n\n".join([doc.page_content for doc in documents])
        
        # Use the chain with invoke instead of direct call
        result = self.chain.invoke({"context": context, "question": query})
        
        return {
            "answer": result,
            "sources": [doc.metadata.get("source", "Unknown") for doc in documents]
        }

    def get_answer_from_file(self, question: str, context: str) -> str:
        """獲取問題的答案"""
        return self.chain.invoke({"context": context, "question": question}) 