import httpx, asyncio
from app.main import app

async def test():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
        r = await client.get('/api/v1/agents/analytics/cost')
        body = r.json()
        print(f'/api/v1/agents/analytics/cost: {r.status_code} - type: {type(body).__name__}')
        if isinstance(body, dict):
            print(f'  keys: {list(body.keys())}')
            for k, v in body.items():
                print(f'    {k}: {v} ({type(v).__name__})')

asyncio.run(test())