from typing import List
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.schema import Document
from langchain_community.document_loaders import TextLoader, PyPDFLoader

class DocumentLoader:
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=len,
            is_separator_regex=False,
        )

    def load_from_text(self, text: str, filename: str) -> List[Document]:
        """從文本內容創建文檔並分塊"""
        document = Document(
            page_content=text,
            metadata={"source": filename}
        )
        return self.text_splitter.split_documents([document])

    def load_markdown(self, file_path: str) -> List[Document]:
        """載入 Markdown 文件並分塊"""
        loader = TextLoader(file_path, encoding='utf-8')
        documents = loader.load()
        return self.text_splitter.split_documents(documents)

    def load_pdf(self, file_path: str) -> List[Document]:
        """載入 PDF 文件並分塊"""
        loader = PyPDFLoader(file_path)
        documents = loader.load()
        return self.text_splitter.split_documents(documents)

    def load_document(self, file_path: str) -> List[Document]:
        """根據文件類型自動選擇載入器"""
        if file_path.lower().endswith('.md'):
            return self.load_markdown(file_path)
        elif file_path.lower().endswith('.pdf'):
            return self.load_pdf(file_path)
        else:
            raise ValueError(f"Unsupported file type: {file_path}") 