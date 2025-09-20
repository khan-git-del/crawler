#!/usr/bin/env python3
import asyncio
import os
import asyncpg

async def setup():
    conn = await asyncpg.connect(os.environ['DATABASE_URL'])
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS repositories (
            id BIGINT PRIMARY KEY,
            full_name VARCHAR(255) UNIQUE,
            star_count INTEGER,
            created_at TIMESTAMPTZ
        )
    ''')
    await conn.close()

if __name__ == '__main__':
    asyncio.run(setup())
