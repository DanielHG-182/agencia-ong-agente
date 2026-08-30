# RAG Proposal Assistant

RAG Proposal Assistant is a document intelligence application designed to support NGOs and proposal management professionals in drafting evidence-based funding proposals.

The application processes reference documents, divides them into structured chunks, stores their embeddings in a vector database, retrieves relevant evidence, and uses a large language model to generate proposal sections grounded in the available sources.

## Why This Project?

Preparing funding proposals often requires reviewing long application forms, programme documentation, previous materials, and internal organisational information.

This project explores how Retrieval-Augmented Generation (RAG) can help proposal teams:

- retrieve relevant information from multiple documents;
- generate structured proposal sections;
- reduce unsupported or invented claims;
- maintain project-specific writing directives;
- review and approve generated sections;
- export the final proposal to Microsoft Word;
- evaluate retrieval and generation quality.

## Current Status

This repository is an active portfolio project focused on applied RAG engineering.

The core document-processing, chunking, indexing, retrieval, drafting, evaluation, and export workflows are implemented. Additional testing, documentation, evaluation reporting, and deployment work is ongoing.

## How It Works

RAG Proposal Assistant implements an end-to-end Retrieval-Augmented Generation pipeline.

```text
Source documents
      |
      v
Document conversion
      |
      v
Structure-aware hierarchical chunking
      |
      v
OpenAI embeddings
      |
      v
ChromaDB vector index
      |
      v
Semantic retrieval
      |
      v
Project context and writing directives
      |
      v
Grounded section generation
      |
      v
Human review and approval
      |
      v
Microsoft Word export
```

### Pipeline Stages

The pipeline can be executed through the command line using the following stages:


| Stage            | Purpose                                                         |
| ---------------- | --------------------------------------------------------------- |
| `conversion`     | Extracts and normalises content from source documents           |
| `chunking`       | Divides processed documents into structured, retrievable chunks |
| `indexing`       | Generates embeddings and stores chunks in ChromaDB              |
| `retrieval-test` | Tests semantic retrieval for a user query                       |
| `draft-test`     | Generates a proposal section using retrieved evidence           |
| `export-test`    | Exports approved sections to a Microsoft Word document          |
| `eval-generate`  | Produces a synthetic evaluation dataset                         |
| `evaluate`       | Evaluates retrieval and generation quality using RAG metrics    |


The Streamlit interface provides a visual workflow for managing projects, reviewing sections, generating drafts, and exporting documents.

## Key Features

- Multi-format document ingestion for PDF, DOCX and TXT files
- Structure-aware document processing with table extraction
- Structure-aware hierarchical chunking with overlap, metadata, and stable identifiers
- OpenAI embeddings for document indexing and query representation
- Persistent vector storage with ChromaDB
- Semantic retrieval of relevant proposal evidence
- Evidence-grounded proposal section generation
- Project-specific writing directives and context injection
- Human review and approval workflow through Streamlit
- Microsoft Word export with optional document templates
- Synthetic evaluation dataset generation
- RAG evaluation with RAGAS metrics
- Retry and backoff handling for OpenAI API failures
- Project isolation through configurable folder structures

## Tech Stack


| Area                       | Technology                           |
| -------------------------- | ------------------------------------ |
| Language                   | Python                               |
| User interface             | Streamlit                            |
| LLM and embeddings         | OpenAI API                           |
| Vector database            | ChromaDB                             |
| PDF processing             | PyMuPDF and pdfplumber               |
| Word processing            | python-docx                          |
| Evaluation                 | RAGAS, Hugging Face Datasets, Pandas |
| LLM evaluation integration | LangChain OpenAI                     |
| Reliability                | Tenacity                             |
| Configuration              | python-dotenv                        |


## Installation

### 1. Clone the repository

```bash
git clone https://github.com/DanielHG-182/agencia-ong-agente.git
cd agencia-ong-agente
```

### 2. Create a virtual environment

On Windows:

```powershell
python -m venv .venv
.venv\Scripts\activate
```

On macOS or Linux:

```bash
python -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure environment variables

Copy the example configuration:

On Windows:

```powershell
Copy-Item .env.example .env
```

On macOS or Linux:

```bash
cp .env.example .env
```

Then open `.env` and add your OpenAI API key:

```dotenv
OPENAI_API_KEY=your_api_key_here
```

The remaining variables already include sensible defaults and only need to be changed when using a custom folder structure, model, retrieval configuration, or Word template.

## Running the Application

### Streamlit interface

On Windows, you can use:

```powershell
.\startApp.bat
```

Or launch Streamlit directly:

```powershell
streamlit run app.py
```

### Command-line pipeline

General syntax:

```powershell
python main.py --stage <stage> --project <project_name>
```

Example:

```powershell
python main.py --stage indexing --project demo_project
```

## Repository Structure

```text
.
|-- app.py
|-- main.py
|-- requirements.txt
|-- .env.example
|-- startApp.bat
|
|-- projects/
|   `-- demo_project/
|       |-- config/
|       |   |-- directives.md
|       |   `-- index.json
|       |-- data/
|       |   |-- raw/
|       |   |-- processed/
|       |   |-- chunks/
|       |   `-- evaluation/
|       |-- vector_db/
|       |-- output/
|       `-- progress.json
|
|-- scripts/
|   |-- document_processor.py
|   |-- chunker.py
|   |-- indexer.py
|   |-- retriever.py
|   |-- redactor.py
|   |-- exporter.py
|   |-- generate_synthetic_dataset.py
|   |-- evaluator.py
|   `-- utils/
|       `-- paths.py
|
`-- views/
    |-- home.py
    |-- sections_manager.py
    |-- redactor.py
    `-- export.py
```

### Main Components

- `app.py` starts the Streamlit application and handles page navigation.
- `main.py` exposes the command-line pipeline stages.
- `scripts/document_processor.py` extracts and normalises document content.
- `scripts/chunker.py` creates structured chunks with metadata and stable identifiers.
- `scripts/indexer.py` generates embeddings and stores them in ChromaDB.
- `scripts/retriever.py` performs semantic evidence retrieval.
- `scripts/redactor.py` builds grounded prompts and generates proposal sections.
- `scripts/exporter.py` creates Microsoft Word documents.
- `scripts/generate_synthetic_dataset.py` creates question-answer pairs for evaluation.
- `scripts/evaluator.py` evaluates retrieval and generation performance.
- `views/` contains the Streamlit interface.
- `projects/` isolates configuration, documents, indexes, outputs, and progress by project.

Generated data, source documents, vector databases, proposal content, and runtime progress files are excluded from version control.

## Security and Privacy

This repository does not include real proposal documents, generated project content, API keys, vector databases, or runtime progress files.

Sensitive and generated resources are excluded through `.gitignore`, including:

- `.env` files and Streamlit secrets;
- source PDF and Word documents;
- processed documents and chunks;
- ChromaDB indexes;
- generated outputs;
- project writing directives;
- runtime progress files;
- downloaded machine learning models.

Project names are validated before paths are created to prevent path traversal outside the configured projects directory.

OpenAI API credentials are loaded from environment variables and are never hardcoded or printed by the application.

Static security analysis is performed with Bandit. At the time of the latest review, Bandit reported no issues in the application source code.

## Current Limitations

- The application currently depends on OpenAI for embeddings and text generation.
- Document conversion and chunking still support global paths in addition to the multi-project structure.
- Retrieval currently relies primarily on vector similarity and does not yet include hybrid search.
- Generated proposal sections require human review before use.
- Evaluation uses synthetic question-answer datasets and should be complemented with expert-reviewed test cases.
- The Streamlit interface is designed for local use and does not yet include user authentication.
- Automated tests and continuous integration are not yet implemented.
- Deployment instructions and a public hosted demo are not yet available.

## Evaluation

The project includes an evaluation pipeline based on synthetic question-answer pairs and RAGAS metrics.

An initial five-question evaluation was conducted using:

* `text-embedding-3-small` for embeddings;
* `gpt-4o-mini` as the evaluation model;
* ChromaDB retrieval;
* `top_k=4`;
* chunks configured with a size of 500 and an overlap of 50.

### Preliminary Results

| Category               | Faithfulness | Answer Relevancy | Context Recall | Context Precision |
| ---------------------- | -----------: | ---------------: | -------------: | ----------------: |
| Factual questions      |         0.83 |             0.94 |           1.00 |              0.94 |
| Unanswerable questions |         0.00 |             0.00 |           1.00 |              0.17 |

Observed end-to-end pipeline latency ranged from approximately 3.30 to 4.44 seconds per question. Retrieval took approximately 0.88 to 1.84 seconds, while answer generation took approximately 2.20 to 3.10 seconds.

These preliminary results suggest that the system retrieves and answers factual questions effectively when the required evidence is present. However, performance on unanswerable questions remains weak, indicating that refusal logic and insufficient-context detection require further improvement.

The current evaluation set contains only five questions. These figures should therefore be treated as an initial diagnostic rather than as a statistically meaningful benchmark.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.