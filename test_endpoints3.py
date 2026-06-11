import httpx, asyncio
from app.main import app

async def test():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
        r = await client.get('/api/v1/agents/analytics/leaderboard?top_n=5')
        body = r.json()
        print(f'/api/v1/agents/analytics/leaderboard: {r.status_code} - array len: {len(body) if isinstance(body, list) else "N/A"}')
        if isinstance(body, list) and body:
            print(f'  First item keys: {list(body[0].keys())}')

asyncio.run(test())