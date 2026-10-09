
from pathlib import Path
import re

ARTICLES_DIR = Path(__file__).resolve().parent / "data" / "articles"

def main():
    files = sorted(ARTICLES_DIR.glob("*.md"))

    if not files:
        raise SystemExit("ERROR: No Markdown articles found.")

    problems = []
    total_chars = 0
    total_links = 0
    total_images = 0

    for path in files:
        content = path.read_text(encoding="utf-8")
        total_chars += len(content)

        if not content.strip().startswith("# "):
            problems.append(f"{path.name}: missing title heading")

        if "Article URL:" not in content:
            problems.append(f"{path.name}: missing Article URL")

        if len(content.strip()) < 100:
            problems.append(f"{path.name}: suspiciously short content")

        total_links += len(
            re.findall(r"(?<!!)\[[^\]]+\]\(https?://[^)]+\)", content)
        )
        total_images += len(
            re.findall(r"!\[[^\]]*\]\(https?://[^)]+\)", content)
        )

    print(f"Markdown files: {len(files)}")
    print(f"Total characters: {total_chars:,}")
    print(f"Markdown links: {total_links}")
    print(f"Markdown images: {total_images}")
    print(f"Validation issues: {len(problems)}")

    for problem in problems[:30]:
        print(f"  - {problem}")

    if problems:
        raise SystemExit("Validation failed; inspect the issues above.")

    print("Validation passed.")

if __name__ == "__main__":
    main()