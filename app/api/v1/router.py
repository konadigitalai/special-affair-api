from fastapi import APIRouter

from app.modules.catalog.router import collections_router, router as catalog_router, search_router
from app.modules.content.router import router as content_router

router = APIRouter()
router.include_router(catalog_router)
router.include_router(collections_router)
router.include_router(search_router)
router.include_router(content_router)
