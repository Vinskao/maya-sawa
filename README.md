# Maya-Sawa: Document Q&A System

A powerful document question-answering system built with LangChain and ChromaDB. This system allows you to ask questions about your markdown documents and get AI-powered answers based on the content.

## Features

- Document ingestion and processing
- Text chunking with overlap
- Vector storage using ChromaDB
- OpenAI embeddings and chat model integration
- Interactive CLI interface for Q&A

## Prerequisites

- Python 3.9 or higher
- Poetry (Python package manager)
- OpenAI API key

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/maya-sawa.git
cd maya-sawa
```

2. Install dependencies using Poetry:
```bash
poetry install
```

3. Create a `.env` file:
```bash
cp .env.example .env
```

4. Edit `.env` and add your OpenAI API key:
```
OPENAI_API_KEY=sk-your-api-key-here
```

## Usage

1. Place your markdown documents in the `docs/` directory.

2. Process the documents and create the vector store:
```bash
poetry run python ingest.py
```

3. Start the Q&A chat interface:
```bash
poetry run python qa_chat.py
```

4. Ask questions about your documents! Type 'exit' to quit.

## Project Structure

```
maya-sawa/
├── docs/                # Markdown documents
├── chroma_db/           # ChromaDB vector store
├── ingest.py           # Document processing script
├── qa_chat.py          # Q&A chat interface
├── .env.example        # Environment variables template
├── pyproject.toml      # Poetry project configuration
└── README.md           # This file
```

## How It Works

1. **Document Processing** (`ingest.py`):
   - Reads markdown files from the `docs/` directory
   - Splits documents into chunks using RecursiveCharacterTextSplitter
   - Creates embeddings using OpenAI's text-embedding-3-small model
   - Stores vectors in ChromaDB

2. **Q&A System** (`qa_chat.py`):
   - Loads the vector store
   - Uses GPT-3.5-turbo for generating answers
   - Provides source documents for answers
   - Interactive CLI interface for questions

## License

MIT License
