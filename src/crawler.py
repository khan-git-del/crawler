import requests
import time
import os
import psycopg2
from datetime import datetime

token = os.environ["GITHUB_TOKEN"]
headers = {"Authorization": f"bearer {token}"}

conn = psycopg2.connect(
    host="localhost",
    port="5432",
    dbname="postgres",
    user="postgres",
    password=os.environ.get("POSTGRES_PASSWORD", "postgres")
)
cur = conn.cursor()

def fetch_repos(search_query):
    repos = []
    cursor = None
    has_next_page = True
    repo_count = 0
    while has_next_page and repo_count < 1000:
        after = f'"{cursor}"' if cursor else "null"
        gql = """
        query {
          search(query: "%s", type: REPOSITORY, first: 100, after: %s) {
            edges {
              node {
                ... on Repository {
                  nameWithOwner
                  stargazerCount
                }
              }
            }
            pageInfo {
              endCursor
              hasNextPage
            }
          }
          rateLimit {
            cost
            remaining
            resetAt
          }
        }
        """ % (search_query, after)
        
        retries = 3
        while retries > 0:
            try:
                response = requests.post("https://api.github.com/graphql", json={"query": gql}, headers=headers)
                response.raise_for_status()
                data = response.json()
                if "errors" in data:
                    raise Exception(data["errors"])
                break
            except Exception as e:
                print(f"Error: {e}. Retrying in {5 * (4 - retries)}s...")
                time.sleep(5 * (4 - retries))
                retries -= 1
        else:
            print("Max retries exceeded.")
            return repos
        
        rate_data = data["data"]["rateLimit"]
        if rate_data["remaining"] < 100:
            reset_time = datetime.fromisoformat(rate_data["resetAt"].replace("Z", "+00:00"))
            sleep_sec = (reset_time - datetime.utcnow()).total_seconds() + 10
            print(f"Rate low. Sleeping {sleep_sec}s until {rate_data['resetAt']}.")
            time.sleep(max(0, sleep_sec))
        
        edges = data["data"]["search"]["edges"]
        for edge in edges:
            repo = edge["node"]
            repos.append((repo["nameWithOwner"], repo["stargazerCount"]))
        
        cursor = data["data"]["search"]["pageInfo"]["endCursor"]
        has_next_page = data["data"]["search"]["pageInfo"]["hasNextPage"]
        repo_count += len(edges)

    return repos

total_repos = 0
for i in range(100):  # Adjust to lower for testing (e.g., 10 for ~10k repos)
    print(f"Fetching for stars:{i}")
    repos = fetch_repos(f"stars:{i} sort:stars-desc")
    for full_name, stars in repos:
        cur.execute("""
        INSERT INTO repositories (full_name, stars) 
        VALUES (%s, %s) 
        ON CONFLICT (full_name) DO UPDATE SET stars = EXCLUDED.stars, updated_at = CURRENT_TIMESTAMP;
        """, (full_name, stars))
    conn.commit()
    total_repos += len(repos)
    print(f"Total repos so far: {total_repos}")
    if total_repos >= 100000:
        break

cur.close()
conn.close()
