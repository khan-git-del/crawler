import os
import time
import psycopg2
import requests
from datetime import datetime

# --- GitHub Config ---
GITHUB_API = "https://api.github.com/graphql"
TOKEN = os.getenv("GITHUB_TOKEN")

# --- Postgres Config ---
DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_NAME = os.getenv("POSTGRES_DB", "crawlerdb")
DB_USER = os.getenv("POSTGRES_USER", "postgres")
DB_PASS = os.getenv("POSTGRES_PASSWORD", "postgres")
DB_PORT = os.getenv("POSTGRES_PORT", "5432")

# --- Connect to Postgres ---
conn = psycopg2.connect(
    host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS, port=DB_PORT
)
cursor = conn.cursor()


def init_db():
    """Initialize the repositories table if not exists."""
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS repositories (
        repo_id TEXT PRIMARY KEY,
        name TEXT,
        stars INT,
        last_updated TIMESTAMP
    );
    """)
    conn.commit()


def safe_request(query, variables):
    """Make GitHub API requests with rate limit handling."""
    while True:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        response = requests.post(GITHUB_API, json={"query": query, "variables": variables}, headers=headers)
        data = response.json()

        # Retry on rate limits
        if "errors" in data:
            errors = str(data["errors"])
            if "rate limit" in errors.lower():
                print("⚠️ Rate limit hit. Sleeping 60s...")
                time.sleep(60)
                continue
            else:
                print("❌ Error:", errors)
                return None
        return data


def crawl_repos(max_repos=100000):
    """Crawl GitHub repositories and store stars into Postgres."""
    query = """
    query ($cursor: String) {
      search(query: "stars:>0", type: REPOSITORY, first: 100, after: $cursor) {
        pageInfo {
          endCursor
          hasNextPage
        }
        nodes {
          id
          nameWithOwner
          stargazerCount
        }
      }
    }
    """

    cursor_val = None
    collected = 0

    while collected < max_repos:
        variables = {"cursor": cursor_val}
        data = safe_request(query, variables)
        if not data:
            break

        repos = data["data"]["search"]["nodes"]

        for repo in repos:
            repo_id = repo["id"]
            name = repo["nameWithOwner"]
            stars = repo["stargazerCount"]

            # ✅ Upsert: insert or update existing row
            cursor.execute("""
            INSERT INTO repositories (repo_id, name, stars, last_updated)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (repo_id)
            DO UPDATE SET stars = EXCLUDED.stars, last_updated = EXCLUDED.last_updated;
            """, (repo_id, name, stars, datetime.utcnow()))

            collected += 1
            if collected >= max_repos:
                break

        conn.commit()

        page_info = data["data"]["search"]["pageInfo"]
        if not page_info["hasNextPage"]:
            break
        cursor_val = page_info["endCursor"]

        print(f"✅ Collected {collected} repos...")

    print(f"🎉 Done! Total repos collected: {collected}")


if __name__ == "__main__":
    init_db()
    crawl_repos(100000)
    conn.close()
