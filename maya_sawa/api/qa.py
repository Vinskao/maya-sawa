from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import List
import os
from ..core.loader import DocumentLoader
from ..core.embed import VectorStore
from ..core.qa_chain import QAChain

router = APIRouter(prefix="/qa", tags=["Q&A"])

# 初始化組件
loader = DocumentLoader()
vector_store = VectorStore()
qa_chain = QAChain()

class Question(BaseModel):
    text: str

@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """上傳文件並處理"""
    try:
        # 保存上傳的文件
        file_path = f"data/uploads/{file.filename}"
        os.makedirs("data/uploads", exist_ok=True)
        
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)

        # 載入並處理文件
        documents = loader.load_document(file_path)
        
        # 添加到向量存儲
        vector_store.add_documents(documents)
        
        return {"message": f"Successfully processed {file.filename}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/query")
async def ask_question(question: Question):
    """處理問題並返回答案"""
    try:
        # 搜尋相關文檔
        relevant_docs = vector_store.similarity_search(question.text)
        
        # 獲取答案
        result = qa_chain.get_answer(question.text, relevant_docs)
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) 