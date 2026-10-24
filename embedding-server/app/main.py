from fastapi import FastAPI
from routers import embed, rerank

app = FastAPI(title="Embedding Server")
app.include_router(embed.router)
app.include_router(rerank.router)