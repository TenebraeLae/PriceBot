import redis.asyncio as redis

SEARCH_CACHE_PREFIX = "pricebot:search:"


async def invalidate_search_cache(redis_url: str | None) -> None:
    if not redis_url:
        return
    client: redis.Redis | None = None
    try:
        client = redis.from_url(
            redis_url,
            socket_connect_timeout=0.25,
            socket_timeout=0.25,
        )
        pipe = client.pipeline(transaction=False)
        pending = 0
        async for key in client.scan_iter(match=f"{SEARCH_CACHE_PREFIX}*"):
            pipe.unlink(key)
            pending += 1
            if pending % 500 == 0:
                await pipe.execute()
        if pending:
            await pipe.execute()
    except Exception:
        return
    finally:
        if client is not None:
            await client.aclose()
