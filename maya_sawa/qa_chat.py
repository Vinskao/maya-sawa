import os
from dotenv import load_dotenv
from langchain_community.vectorstores import Chroma
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate

# Load environment variables
load_dotenv()

def initialize_qa_chain():
    """Initialize the QA chain with the vector store."""
    # Initialize embeddings and load the vector store
    embeddings = OpenAIEmbeddings()
    vectorstore = Chroma(
        persist_directory="chroma_db",
        embedding_function=embeddings
    )

    # Create the QA chain
    qa_chain = RetrievalQA.from_chain_type(
        llm=ChatOpenAI(temperature=0, model_name="gpt-3.5-turbo"),
        chain_type="stuff",
        retriever=vectorstore.as_retriever(search_kwargs={"k": 3}),
        return_source_documents=True,
        chain_type_kwargs={
            "prompt": PromptTemplate(
                template="""Use the following pieces of context to answer the question at the end. 
                If you don't know the answer, just say that you don't know, don't try to make up an answer.

                Context: {context}

                Question: {question}
                Answer: """,
                input_variables=["context", "question"]
            )
        }
    )
    return qa_chain

def main():
    print("Initializing Q&A system...")
    qa_chain = initialize_qa_chain()
    print("\nWelcome to Maya-Sawa Q&A System!")
    print("Type 'exit' to quit the chat.")
    
    while True:
        question = input("\nYour question: ").strip()
        if question.lower() == 'exit':
            break
            
        if not question:
            continue
            
        try:
            result = qa_chain({"query": question})
            print("\nAnswer:", result["result"])
            print("\nSources:")
            for doc in result["source_documents"]:
                print(f"- {doc.metadata.get('source', 'Unknown source')}")
        except Exception as e:
            print(f"Error: {str(e)}")

if __name__ == "__main__":
    main() 