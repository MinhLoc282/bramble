# Knowledge Sync Pipeline

A Python pipeline that scrapes the OptiSigns Help Center, converts articles to Markdown, and incrementally syncs them to an OpenAI vector store.

## Features

* **Scraping:** Retrieves published English Help Center articles through the Zendesk API and converts them to Markdown, preserving headings, links, lists, and images.
* **Validation:** Checks the generated Markdown collection for content and formatting issues.
* **Knowledge base:** Uploads Markdown files programmatically through the OpenAI API. OpenAI manages document chunking and indexing.
* **Incremental sync:** Uses SHA-256 hashes and a persistent JSON manifest to identify added, updated, unchanged, and removed articles.
* **Logging:** Records fetched, added, updated, skipped, deleted, and failed counts.

## Setup

Requirements: Python 3.11+, Docker, and an OpenAI API key.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create `.env` from `.env.sample` and configure:

```dotenv
OPENAI_API_KEY=your_openai_api_key
OPENAI_VECTOR_STORE_ID=your_vector_store_id
```

For the initial upload, leave `OPENAI_VECTOR_STORE_ID` empty and run:

```powershell
python upload_to_openai.py
```

This creates a vector store, uploads the Markdown files through the API, and saves the vector store ID in `.env`.

## Run locally

```powershell
python main.py
python validate_articles.py
```

Logs are written to `logs/`; the sync manifest is stored in `sync_state.json`.

## Run with Docker

Build the image:

```powershell
docker build -t opti-helper-sync .
```

For a one-off run:

```powershell
docker run --rm --env-file .env opti-helper-sync
```

For repeated runs with persistent sync state and logs, create named volumes once:

```powershell
docker volume create opti-sync-state
docker volume create opti-sync-logs
```

Run the sync using those volumes:

```powershell
docker run --rm --env-file .env `
  --mount source=opti-sync-state,target=/app/state `
  --mount source=opti-sync-logs,target=/app/logs `
  opti-helper-sync
```

The first persistent run reconciles the existing vector store and creates a manifest. Subsequent runs reuse the manifest to detect changes and skip unchanged articles. The one-off command does not persist the manifest after the container exits.

## Verification

* Scraped and validated **415 Markdown articles**, with zero validation issues.
* Uploaded **415 files** through the OpenAI API; all completed processing.
* Tested “How do I add a YouTube video?” in the OpenAI Playground using File Search and article citations.
* Local and Docker sync tests detected 415 unchanged articles with zero failures.

**Assistant screenshot:** [YouTube answer with citations](docs/optibot-youtube-answer.png)

**Daily job:** [GitHub Actions workflow](https://github.com/MinhLoc282/bramble/actions)

Open the workflow's latest successful run to view its logs and download the `daily-sync-logs` artifact. The daily schedule runs at 02:00 UTC (09:00 Vietnam time).