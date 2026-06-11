import httpx, asyncio
from app.main import app

async def test():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
        endpoints = [
            '/api/v1/compliance-risk/assessments?page=1&page_size=2',
            '/api/v1/forecasting/forecasts',
            '/api/v1/review/tasks?page=1&page_size=2',
            '/api/v1/recommendations?page=1&page_size=2',
            '/api/v1/audit/integrity',
        ]
        for ep in endpoints:
            r = await client.get(ep)
            body = r.json()
            if isinstance(body, dict):
                print(f'{ep}: {r.status_code} - keys: {list(body.keys())}')
            else:
                print(f'{ep}: {r.status_code} - array len: {len(body)}')

asyncio.run(test())