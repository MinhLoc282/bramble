
import os
from contextlib import ExitStack
from pathlib import Path

from dotenv import load_dotenv, set_key
from openai import OpenAI, DefaultHttpx2Client


BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
ARTICLES_DIR = BASE_DIR / "data" / "articles"


def main() -> None:
    load_dotenv(ENV_PATH)

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing from .env")

    # Prevent the unsupported local SOCKS proxy from being detected.
    client = OpenAI(
        api_key=api_key,
        http_client=DefaultHttpx2Client(trust_env=False),
    )

    article_paths = sorted(ARTICLES_DIR.glob("*.md"))

    if not article_paths:
        raise RuntimeError(f"No Markdown files found in {ARTICLES_DIR}")

    if len(article_paths) > 500:
        raise RuntimeError(
            "This initial uploader supports at most 500 files per batch."
        )

    existing_id = os.getenv("OPENAI_VECTOR_STORE_ID", "").strip()
    if existing_id:
        raise RuntimeError(
            "OPENAI_VECTOR_STORE_ID is already set. "
            "Upload stopped to prevent accidental duplicate uploads. "
            "Use the existing vector store or handle recovery explicitly."
        )

    print(f"Markdown files found: {len(article_paths)}")
    print("Creating vector store...")

    vector_store = client.vector_stores.create(
        name="OptiSigns Help Center"
    )

    # Save the ID immediately so it isn't lost if uploading fails.
    set_key(ENV_PATH, "OPENAI_VECTOR_STORE_ID", vector_store.id, quote_mode="never",)

    print(f"Vector store created: {vector_store.id}")
    print("Uploading files and waiting for processing...")

    with ExitStack() as stack:
        files = [
            stack.enter_context(path.open("rb"))
            for path in article_paths
        ]

        batch = client.vector_stores.file_batches.upload_and_poll(
            vector_store_id=vector_store.id,
            files=files,
            max_concurrency=5,
            poll_interval_ms=2000,
        )

    counts = batch.file_counts

    print("\nUpload batch finished.")
    print(f"Batch status: {batch.status}")
    print(f"Total files: {counts.total}")
    print(f"Completed: {counts.completed}")
    print(f"Failed: {counts.failed}")
    print(f"In progress: {counts.in_progress}")
    print(f"Cancelled: {counts.cancelled}")
    print(f"Vector store ID: {vector_store.id}")

    if counts.failed or counts.completed != len(article_paths):
        raise RuntimeError(
            "Not all files were processed successfully. "
            "Keep the vector store ID and inspect the batch before retrying."
        )

    print("\nAll Markdown articles were uploaded and processed.")


if __name__ == "__main__":
    main()