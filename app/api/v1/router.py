from fastapi import APIRouter

from app.modules.catalog.router import collections_router, router as catalog_router, search_router
from app.modules.content.router import router as content_router
from app.ai.shopping_copilot.router import router as copilot_router
from app.modules.cart.router import router as cart_router
from app.modules.checkout.router import router as checkout_router

router = APIRouter()
router.include_router(catalog_router)
router.include_router(collections_router)
router.include_router(search_router)
router.include_router(content_router)
router.include_router(copilot_router)
router.include_router(cart_router)
router.include_router(checkout_router)
