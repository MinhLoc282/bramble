
import hashlib
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI, DefaultHttpx2Client

from scraper.zendesk import fetch_articles, make_slug, save_articles


BASE_DIR = Path(__file__).resolve().parent
ARTICLES_DIR = BASE_DIR / "data" / "articles"
LOG_DIR = BASE_DIR / "logs"
STATE_PATH = BASE_DIR / "sync_state.json"
ENV_PATH = BASE_DIR / ".env"

def configure_runtime_paths() -> None:
    global LOG_DIR, STATE_PATH

    state_dir = Path(os.getenv("SYNC_STATE_DIR", str(BASE_DIR)))
    LOG_DIR = Path(os.getenv("SYNC_LOG_DIR", str(BASE_DIR / "logs")))

    state_dir.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    STATE_PATH = state_dir / "sync_state.json"


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"sync-{datetime.now():%Y-%m-%d}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
        force=True,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_state(state: dict) -> None:
    temporary_path = STATE_PATH.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(state, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(STATE_PATH)


def list_remote_files(client, vector_store_id: str) -> list[dict]:
    """List files currently attached to the existing vector store."""
    remote_files = []
    after = None

    while True:
        kwargs = {"vector_store_id": vector_store_id, "limit": 100}
        if after:
            kwargs["after"] = after

        page = client.vector_stores.files.list(**kwargs)

        for item in page.data:
            metadata = client.files.retrieve(item.id)
            remote_files.append({
                "file_id": item.id,
                "filename": metadata.filename,
            })

        if not page.has_more or not page.data:
            break

        after = page.data[-1].id

    return remote_files


def article_id_from_filename(filename: str) -> str | None:
    match = re.search(r"-(\d+)\.md$", filename)
    return match.group(1) if match else None


def bootstrap_state(
    client,
    vector_store_id: str,
    current_paths: dict[str, Path],
) -> dict:
    """
    Recover the initial manifest from the files already uploaded.
    Matching filenames are treated as the initial content baseline.
    """
    logging.info("No sync manifest found; reconciling existing remote files.")

    state = {"articles": {}}
    remote_files = list_remote_files(client, vector_store_id)

    for remote in remote_files:
        article_id = article_id_from_filename(remote["filename"])
        if not article_id:
            logging.warning(
                "Cannot identify article ID for remote file %s",
                remote["filename"],
            )
            continue

        local_path = current_paths.get(article_id)
        same_filename = (
            local_path is not None
            and local_path.name == remote["filename"]
        )

        state["articles"][article_id] = {
            "filename": remote["filename"],
            "sha256": sha256_file(local_path) if same_filename else "",
            "file_id": remote["file_id"],
        }

    save_state(state)
    logging.info("Reconciled %d existing remote files.", len(remote_files))
    return state


def remove_remote_file(client, vector_store_id: str, file_id: str) -> None:
    """Detach a file from the vector store, then delete its uploaded file."""
    client.vector_stores.files.delete(
        vector_store_id=vector_store_id,
        file_id=file_id,
    )

    try:
        client.files.delete(file_id)
    except Exception:
        # The vector-store association has already been removed.
        logging.warning(
            "Removed vector-store association but could not delete "
            "underlying file %s.",
            file_id,
            exc_info=True,
        )


def upload_article(client, vector_store_id: str, path: Path) -> str:
    """Upload one Markdown file and wait until File Search has processed it."""
    with path.open("rb") as file:
        uploaded = client.files.create(
            file=file,
            purpose="assistants",
        )

    try:
        result = client.vector_stores.files.create_and_poll(
            vector_store_id=vector_store_id,
            file_id=uploaded.id,
            poll_interval_ms=2000,
        )

        if result.status != "completed":
            raise RuntimeError(
                f"File processing did not complete for {path.name}: "
                f"{result.status}"
            )

        return uploaded.id

    except Exception:
        # Avoid leaving the new file behind if attachment/processing fails.
        try:
            client.files.delete(uploaded.id)
        except Exception:
            logging.warning(
                "Could not clean up failed upload %s.",
                uploaded.id,
            )
        raise


def main() -> None:
    load_dotenv(ENV_PATH)
    configure_runtime_paths()
    setup_logging()

    api_key = os.getenv("OPENAI_API_KEY")
    vector_store_id = os.getenv("OPENAI_VECTOR_STORE_ID", "").strip()

    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing from .env")

    if not vector_store_id:
        raise RuntimeError("OPENAI_VECTOR_STORE_ID is missing from .env")

    client = OpenAI(
        api_key=api_key,
        http_client=DefaultHttpx2Client(trust_env=False),
    )

    logging.info("Starting OptiSigns daily sync.")

    # Fetch first and reject suspiciously incomplete scrapes.
    articles = fetch_articles()
    if len(articles) < 30:
        raise RuntimeError(
            f"Only {len(articles)} articles fetched; refusing to sync."
        )

    save_articles(articles)

    current_paths = {
        str(article["id"]): ARTICLES_DIR
        / f"{make_slug(article.get('title') or article.get('name') or 'Untitled', article['id'])}.md"
        for article in articles
    }

    if not all(path.exists() for path in current_paths.values()):
        raise RuntimeError("One or more expected Markdown files are missing.")

    if STATE_PATH.exists():
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    else:
        state = bootstrap_state(
            client,
            vector_store_id,
            current_paths,
        )

    known_articles = state.setdefault("articles", {})
    added = updated = skipped = deleted = failed = 0

    for article_id, path in current_paths.items():
        old = known_articles.get(article_id)
        digest = sha256_file(path)

        if (
            old
            and old.get("sha256") == digest
            and old.get("filename") == path.name
            and old.get("file_id")
        ):
            skipped += 1
            continue

        action = "updated" if old else "added"

        try:
            new_file_id = upload_article(
                client,
                vector_store_id,
                path,
            )

            # Replace the old remote file only after the new one is ready.
            if old and old.get("file_id"):
                remove_remote_file(
                    client,
                    vector_store_id,
                    old["file_id"],
                )

            known_articles[article_id] = {
                "filename": path.name,
                "sha256": digest,
                "file_id": new_file_id,
            }
            save_state(state)

            if action == "added":
                added += 1
            else:
                updated += 1

            logging.info("%s: %s", action.capitalize(), path.name)

        except Exception:
            failed += 1
            logging.exception("Failed to sync %s", path.name)

    # Remove articles that are no longer published or returned by the API.
    current_ids = set(current_paths)
    if failed == 0:
        for article_id in list(known_articles):
            if article_id in current_ids:
                continue

            old = known_articles[article_id]
            try:
                if old.get("file_id"):
                    remove_remote_file(
                        client,
                        vector_store_id,
                        old["file_id"],
                    )

                del known_articles[article_id]
                save_state(state)
                deleted += 1
                logging.info("Deleted obsolete article %s", article_id)

            except Exception:
                failed += 1
                logging.exception(
                    "Failed to remove obsolete article %s",
                    article_id,
                )

    else:
        logging.warning(
            "Skipping obsolete-article deletion because %d sync operation(s) failed.",
            failed,
        )

    # Clean up stale local Markdown only if the remote sync succeeded.
    if failed == 0:
        expected_names = {path.name for path in current_paths.values()}
        for path in ARTICLES_DIR.glob("*.md"):
            if path.name not in expected_names:
                path.unlink(missing_ok=True)
    else:
        logging.warning(
            "Skipping stale local Markdown cleanup because the sync had failures."
        )

    logging.info(
        "Sync summary | fetched=%d | added=%d | updated=%d | "
        "skipped=%d | deleted=%d | failed=%d",
        len(articles),
        added,
        updated,
        skipped,
        deleted,
        failed,
    )

    if failed:
        raise RuntimeError(
            f"Sync finished with {failed} failure(s). Check the log."
        )

    logging.info("Daily sync completed successfully.")


if __name__ == "__main__":
    main()