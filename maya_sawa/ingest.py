import os
from pathlib import Path
from typing import List
from dotenv import load_dotenv
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain_community.document_loaders import TextLoader

# Load environment variables
load_dotenv()

def load_documents(directory: str) -> List[str]:
    """Load all markdown files from the specified directory."""
    documents = []
    for file_path in Path(directory).glob("*.md"):
        try:
            loader = TextLoader(str(file_path))
            documents.extend(loader.load())
        except Exception as e:
            print(f"Error loading {file_path}: {e}")
    return documents

def main():
    # Initialize the text splitter
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        length_function=len,
    )

    # Load and split documents
    print("Loading documents...")
    documents = load_documents("docs")
    if not documents:
        print("No documents found in docs/ directory!")
        return

    print(f"Loaded {len(documents)} documents")
    splits = text_splitter.split_documents(documents)
    print(f"Split into {len(splits)} chunks")

    # Initialize embeddings and vector store
    print("Creating vector store...")
    embeddings = OpenAIEmbeddings()
    vectorstore = Chroma.from_documents(
        documents=splits,
        embedding=embeddings,
        persist_directory="chroma_db"
    )
    
    # Persist the vector store
    vectorstore.persist()
    print("Vector store created and persisted successfully!")

if __name__ == "__main__":
    main() 