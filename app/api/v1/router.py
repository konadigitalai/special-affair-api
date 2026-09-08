from fastapi import APIRouter

from app.modules.catalog.router import (
    collections_router,
    router as catalog_router,
    search_router,
)
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

from app.modules.inventory.router import router as inventory_router
from app.modules.customers.router import router as customers_router
from app.modules.returns.router import router as returns_router
from app.modules.fulfillment.router import router as fulfillment_router

router.include_router(inventory_router)
router.include_router(customers_router)
router.include_router(returns_router)
router.include_router(fulfillment_router)

from app.modules.support.router import router as support_router

router.include_router(support_router)

from app.modules.catalog.admin import router as catalog_admin_router
from app.modules.audit.router import router as audit_router

router.include_router(catalog_admin_router)
router.include_router(audit_router)

from app.modules.customers.privacy import router as privacy_router
from app.modules.catalog.media import router as media_router

router.include_router(privacy_router)
router.include_router(media_router)
