from app.main import app
schema = app.openapi()
print("OpenAPI version:", schema.get("openapi"))
print("Total paths:", len(schema.get("paths", {})))
print()
print("Module 4.8 endpoints:")
for path in ["/api/v1/search/dense", "/api/v1/search/bm25", "/api/v1/search/hybrid", "/api/v1/retrieval/metrics", "/api/v1/retrieval/health"]:
    methods = list(schema["paths"][path].keys())
    print("  " + ",".join(methods).upper().ljust(8) + " " + path)
