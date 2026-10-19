from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from src.api.upload import router as upload_router
from src.api.search import router as search_router
from src.api.topics import router as topics_router
from src.api.export import router as export_router

app = FastAPI(
    title="ATNI-ResIST",
    description="Resolution Information Search Tool - Document Ingestion API",
    version="0.1.0"
)

# Mount static files
app.mount("/static", StaticFiles(directory="src/static"), name="static")
app.mount("/assets", StaticFiles(directory="assets"), name="assets")

# Include routers
app.include_router(upload_router)
app.include_router(search_router)
app.include_router(topics_router)
app.include_router(export_router)

@app.get("/")
async def root():
    return RedirectResponse(url="/search")

@app.get("/health")
async def health():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
