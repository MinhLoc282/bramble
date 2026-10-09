
import re
import time
import unicodedata
from pathlib import Path

import requests
from markdownify import markdownify
from bs4 import BeautifulSoup


BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "data" / "articles"

API_URL = (
    "https://support.optisigns.com/"
    "api/v2/help_center/en-us/articles.json"
)
PAGE_SIZE = 100
MIN_ARTICLES = 30


def make_slug(title: str, article_id: int) -> str:
    """Create a filesystem-safe, unique filename."""
    title = unicodedata.normalize("NFKD", title)
    title = title.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")
    return f"{slug[:100] or 'article'}-{article_id}"


def fetch_articles() -> list[dict]:
    """Fetch published English Help Center articles via Zendesk API."""
    session = requests.Session()

    # Bypass the locally detected SOCKS proxy, which breaks requests.
    session.trust_env = False

    articles = []
    next_url = API_URL
    params = {"per_page": PAGE_SIZE}

    while next_url:
        response = session.get(
            next_url,
            params=params,
            timeout=30,
        )
        response.raise_for_status()

        data = response.json()
        batch = data.get("articles", [])

        articles.extend(
            article
            for article in batch
            if not article.get("draft", False)
            and article.get("locale") == "en-us"
        )

        print(
            f"Fetched page {data.get('page', '?')}: "
            f"{len(batch)} articles "
            f"(eligible total: {len(articles)})"
        )

        next_url = data.get("next_page")
        params = None  # The next_page URL already contains pagination.

        if len(articles) >= MIN_ARTICLES and not next_url:
            break

        time.sleep(0.1)

    return articles



def article_to_markdown(article: dict) -> str:
    """Convert an article's HTML body into clean Markdown."""
    title = article.get("title") or article.get("name") or "Untitled"
    body_html = article.get("body") or ""

    soup = BeautifulSoup(body_html, "html.parser")

    # Remove scripts and styling that aren't useful to the knowledge base.
    for element in soup(["script", "style", "noscript"]):
        element.decompose()

    # Headings should not retain redundant bold formatting inside them.
    for heading in soup.find_all(re.compile(r"^h[1-6]$")):
        for bold in heading.find_all(["b", "strong"]):
            bold.unwrap()

    body_md = markdownify(
        str(soup),
        heading_style="ATX",
        bullets="-",
    ).strip()

    article_url = article.get("html_url", "")
    updated_at = article.get("updated_at", "")

    return (
        f"# {title}\n\n"
        f"> Last updated: {updated_at}\n\n"
        f"{body_md}\n\n"
        f"Article URL: {article_url}\n"
    )


def save_articles(articles: list[dict]) -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    saved = 0

    for article in articles:
        article_id = article["id"]
        title = article.get("title") or article.get("name") or "Untitled"
        filename = make_slug(title, article_id) + ".md"
        output_path = OUTPUT_DIR / filename

        markdown = article_to_markdown(article)
        output_path.write_text(markdown, encoding="utf-8")
        saved += 1

    return saved


def main() -> None:
    print("Starting OptiSigns Help Center scraper...")
    articles = fetch_articles()

    if len(articles) < MIN_ARTICLES:
        raise RuntimeError(
            f"Expected at least {MIN_ARTICLES} articles; "
            f"received {len(articles)}."
        )

    saved = save_articles(articles)

    print("\nScraping completed.")
    print(f"Articles fetched: {len(articles)}")
    print(f"Markdown files saved: {saved}")
    print(f"Output directory: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()