"""Import every mapped domain before metadata inspection or worker startup."""

from app.modules.catalog import models as catalog
from app.modules.content import models as content
from app.ai.shopping_copilot import models as copilot
from app.modules.cart import models as cart
from app.modules.checkout import models as checkout
from app.modules.orders import models as orders
from app.modules.payments import models as payments
from app.modules.inventory import models as inventory
from app.modules.pricing import models as pricing
from app.modules.customers import models as customers
from app.modules.approvals import models as approvals
from app.modules.audit import models as audit
from app.modules.returns import models as returns
from app.modules.fulfillment import models as fulfillment
from app.workers import models as workers

from app.modules.support import models as support

from app.modules.promotions import models as promotions
