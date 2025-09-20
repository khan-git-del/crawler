#!/usr/bin/env python3
import asyncio
import os
import csv
import asyncpg
import aiohttp
import click
from datetime import datetime

async def graphql_query(session, token, query, variables):
    async with session.post('https://api.github.com/graphql', json={'query': query, 'variables': variables},
                           headers={'Authorization': f'Bearer {token}'}) as resp:
        return await resp.json()

async def crawl_repos(db_pool, token, target):
    total = 0
    cursor = None
    batch_size = 100
    query = """
    query ($cursor: String, $first: Int!) {
        search(type: REPOSITORY, first: $first, after: $cursor, query: "stars:>0") {
            edges {
                node {
                    id
                    nameWithOwner
                    stargazerCount
                    createdAt
                }
                cursor
            }
            pageInfo {
                endCursor
                hasNextPage
            }
        }
    }
    """
    
    async with aiohttp.ClientSession() as session:
        while total < target:
            variables = {'first': batch_size, 'cursor': cursor}
            result = await graphql_query(session, token, query, variables)
            edges = result.get('data', {}).get('search', {}).get('edges', [])
            if not edges:
                break
            repos = [(edge['node']['id'], edge['node']['nameWithOwner'], edge['node']['stargazerCount'],
                     datetime.fromisoformat(edge['node']['createdAt'].replace('Z', '+00:00')))
                     for edge in edges]
            async with db_pool.acquire() as conn:
                await conn.executemany('''
                    INSERT INTO repositories (id, full_name, star_count, created_at)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (id) DO UPDATE SET star_count = EXCLUDED.star_count
                ''', repos)
            total += len(repos)
            cursor = edges[-1]['cursor'] if result['data']['search']['pageInfo']['hasNextPage'] else None
            if total % 1000 == 0:
                print(f"Crawled {total} repositories")
    
    await db_pool.close()
    print(f"Completed crawl with {total} repositories")

async def export_data(db_pool, output):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch('SELECT full_name, star_count, created_at FROM repositories')
        with open(output, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['full_name', 'star_count', 'created_at'])
            writer.writerows(rows)
    await db_pool.close()
    print(f"Exported data to {output}")

@click.group()
def cli():
    pass

@cli.command()
@click.option('--target', default=100000)
def crawl(target):
    asyncio.run(async_crawl(target))

@cli.command()
@click.option('--output', default='repositories.csv')
def export(output):
    asyncio.run(async_export(output))

async def async_crawl(target):
    db_pool = await asyncpg.create_pool(os.environ['DATABASE_URL'])
    await crawl_repos(db_pool, os.environ['GITHUB_TOKEN'], target)

async def async_export(output):
    db_pool = await asyncpg.create_pool(os.environ['DATABASE_URL'])
    await export_data(db_pool, output)

if __name__ == '__main__':
    cli()
