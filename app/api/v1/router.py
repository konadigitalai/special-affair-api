from fastapi import APIRouter

from app.modules.catalog.router import router as catalog_router

router = APIRouter()
router.include_router(catalog_router)
