from fastapi import FastAPI
from routers import embed

app = FastAPI(title="Embedding Server")
app.include_router(embed.router)