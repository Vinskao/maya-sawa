"""
Markdown Q&A System - 文檔載入器模組

這個模組實現了多種格式文檔的載入和處理功能，負責：
1. 載入不同格式的文檔（Markdown、PDF、文本）
2. 文檔分塊處理
3. 元數據管理
4. 自動格式檢測
5. 文檔預處理

主要功能：
- 多格式文檔支持
- 智能文檔分塊
- 元數據提取
- 字符編碼處理
- 錯誤處理

作者: Maya Sawa Team
版本: 0.1.0
"""

# 標準庫導入
from typing import List

# LangChain 相關導入
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.schema import Document
from langchain_community.document_loaders import TextLoader, PyPDFLoader

class DocumentLoader:
    """
    文檔載入器類
    
    負責載入和處理不同格式的文檔，包括：
    - 文檔格式檢測
    - 文檔分塊處理
    - 元數據管理
    - 字符編碼處理
    """
    
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        """
        初始化文檔載入器
        
        設置文檔分塊的參數，包括：
        - 分塊大小
        - 分塊重疊大小
        
        Args:
            chunk_size (int): 每個分塊的最大字符數，默認 1000
            chunk_overlap (int): 相鄰分塊的重疊字符數，默認 200
        """
        # 初始化遞歸字符分割器
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,  # 分塊大小
            chunk_overlap=chunk_overlap,  # 重疊大小
            length_function=len,  # 長度計算函數
            is_separator_regex=False,  # 是否使用正則表達式分隔符
        )

    def load_from_text(self, text: str, filename: str) -> List[Document]:
        """
        從文本內容創建文檔並分塊
        
        將純文本內容轉換為 LangChain Document 對象，
        並進行智能分塊處理
        
        Args:
            text (str): 文本內容
            filename (str): 文件名（用於元數據）
            
        Returns:
            List[Document]: 分塊後的文檔列表
        """
        # 創建單個文檔對象
        document = Document(
            page_content=text,
            metadata={"source": filename}  # 設置來源元數據
        )
        
        # 使用文本分割器進行分塊
        return self.text_splitter.split_documents([document])

    def load_markdown(self, file_path: str) -> List[Document]:
        """
        載入 Markdown 文件並分塊
        
        使用 TextLoader 載入 Markdown 文件，支持 UTF-8 編碼，
        並進行智能分塊處理
        
        Args:
            file_path (str): Markdown 文件路徑
            
        Returns:
            List[Document]: 分塊後的文檔列表
        """
        # 使用 TextLoader 載入 Markdown 文件，指定 UTF-8 編碼
        loader = TextLoader(file_path, encoding='utf-8')
        documents = loader.load()
        
        # 對載入的文檔進行分塊處理
        return self.text_splitter.split_documents(documents)

    def load_pdf(self, file_path: str) -> List[Document]:
        """
        載入 PDF 文件並分塊
        
        使用 PyPDFLoader 載入 PDF 文件，提取文本內容，
        並進行智能分塊處理
        
        Args:
            file_path (str): PDF 文件路徑
            
        Returns:
            List[Document]: 分塊後的文檔列表
        """
        # 使用 PyPDFLoader 載入 PDF 文件
        loader = PyPDFLoader(file_path)
        documents = loader.load()
        
        # 對載入的文檔進行分塊處理
        return self.text_splitter.split_documents(documents)

    def load_document(self, file_path: str) -> List[Document]:
        """
        根據文件類型自動選擇載入器
        
        根據文件擴展名自動選擇合適的載入器，
        支持 Markdown 和 PDF 格式
        
        Args:
            file_path (str): 文件路徑
            
        Returns:
            List[Document]: 分塊後的文檔列表
            
        Raises:
            ValueError: 當文件格式不支持時拋出異常
        """
        # 根據文件擴展名選擇載入器
        if file_path.lower().endswith('.md'):
            # Markdown 文件
            return self.load_markdown(file_path)
        elif file_path.lower().endswith('.pdf'):
            # PDF 文件
            return self.load_pdf(file_path)
        else:
            # 不支持的文件格式
            raise ValueError(f"Unsupported file type: {file_path}") 