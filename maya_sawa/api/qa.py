from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import List, Optional
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

class UploadResponse(BaseModel):
    message: str
    filename: Optional[str] = None

@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: Optional[UploadFile] = File(None),
    content: Optional[str] = Form(None),
    filename: Optional[str] = Form(None)
):
    """上傳文件或直接上傳文本內容"""
    try:
        if file:
            # 處理文件上傳
            file_path = f"data/uploads/{file.filename}"
            os.makedirs("data/uploads", exist_ok=True)
            
            with open(file_path, "wb") as f:
                content = await file.read()
                f.write(content)
            
            documents = loader.load_document(file_path)
            filename = file.filename
        elif content:
            # 處理直接上傳的文本
            if not filename:
                filename = "direct_upload.md"
            file_path = f"data/uploads/{filename}"
            os.makedirs("data/uploads", exist_ok=True)
            
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            
            documents = loader.load_document(file_path)
        else:
            raise HTTPException(status_code=400, detail="Either file or content must be provided")
        
        # 添加到向量存儲
        vector_store.add_documents(documents)
        
        return UploadResponse(
            message="Successfully processed content",
            filename=filename
        )
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