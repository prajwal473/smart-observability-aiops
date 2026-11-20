from fastapi import FastAPI

from app.core.config import settings
from app.api.ingestion import router as ingestion_router
from app.api.ingestion import collector_router


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Smart Observability Platform Backend API",
)


@app.get("/")
def root():
    return {
        "message": "Smart Observability Backend is running",
        "version": settings.APP_VERSION,
    }


@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "backend-database"}


app.include_router(ingestion_router)
app.include_router(collector_router)