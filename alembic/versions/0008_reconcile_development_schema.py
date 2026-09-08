"""Reconcile the earlier customer-only 0006 schema with commerce 0006.

Some development databases recorded a different 0006 migration containing flat
customer/address records. Preserve those records and legacy columns, add commerce
objects, and synchronize the two customer/address representations. Fresh databases
already containing commerce 0006 are also supported. Never stamp backwards.
"""

from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    return bool(
        op.get_bind().scalar(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=:table AND column_name=:column)"
            ),
            {"table": table, "column": column},
        )
    )


def _constraint_exists(table: str, name: str) -> bool:
    return bool(
        op.get_bind().scalar(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid=to_regclass(:table) AND conname=:name)"
            ),
            {"table": "public." + table, "name": name},
        )
    )


def _trigger(sql: str) -> None:
    words = sql.split()
    name, table = words[2], words[words.index("ON") + 1]
    present = op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid=to_regclass(:table) AND tgname=:name)"
        ),
        {"table": "public." + table, "name": name},
    )
    if not present:
        op.execute(sql)


def _legacy_customer_columns() -> None:
    if not _has_column("customers", "auth0_sub"):
        return
    op.execute(
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS auth_subject VARCHAR(200)"
    )
    op.execute(
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS display_name VARCHAR(200)"
    )
    op.execute("UPDATE customers SET auth_subject=auth0_sub WHERE auth_subject IS NULL")
    op.execute(
        "UPDATE customers SET display_name=name WHERE display_name IS NULL AND name IS NOT NULL"
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION sync_legacy_customer_columns() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                NEW.auth_subject := COALESCE(NEW.auth_subject, NEW.auth0_sub);
                NEW.auth0_sub := COALESCE(NEW.auth0_sub, NEW.auth_subject);
                NEW.display_name := COALESCE(NEW.display_name, NEW.name);
                NEW.name := COALESCE(NEW.name, NEW.display_name);
            ELSE
                IF NEW.auth_subject IS DISTINCT FROM OLD.auth_subject THEN NEW.auth0_sub := NEW.auth_subject;
                ELSIF NEW.auth0_sub IS DISTINCT FROM OLD.auth0_sub THEN NEW.auth_subject := NEW.auth0_sub; END IF;
                IF NEW.display_name IS DISTINCT FROM OLD.display_name THEN NEW.name := NEW.display_name;
                ELSIF NEW.name IS DISTINCT FROM OLD.name THEN NEW.display_name := NEW.name; END IF;
            END IF;
            IF NEW.auth_subject IS DISTINCT FROM NEW.auth0_sub THEN
                RAISE EXCEPTION 'conflicting customer identity columns';
            END IF;
            RETURN NEW;
        END; $$
    """)
    _trigger(
        "CREATE TRIGGER sync_customer_representations BEFORE INSERT OR UPDATE ON customers FOR EACH ROW EXECUTE FUNCTION sync_legacy_customer_columns()"
    )
    op.execute("ALTER TABLE customers ALTER COLUMN auth_subject SET NOT NULL")
    if not _constraint_exists("customers", "uq_customers_auth_subject"):
        op.execute(
            "ALTER TABLE customers ADD CONSTRAINT uq_customers_auth_subject UNIQUE(auth_subject)"
        )


def _legacy_address_columns() -> None:
    if not _has_column("addresses", "full_name"):
        return
    op.execute("ALTER TABLE addresses ADD COLUMN IF NOT EXISTS details JSONB")
    op.execute("""
        UPDATE addresses SET details=jsonb_build_object(
            'full_name',full_name,'street',street,'city',city,'state',state,
            'pin_code',pin_code,'country',country,'label',label,'phone',phone,'is_default',is_default
        ) WHERE details IS NULL
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION sync_legacy_address_columns() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE use_details boolean;
        BEGIN
            IF TG_OP = 'INSERT' THEN use_details := NEW.details IS NOT NULL;
            ELSE use_details := NEW.details IS DISTINCT FROM OLD.details; END IF;
            IF use_details THEN
                NEW.full_name := COALESCE(NEW.details->>'full_name',NEW.full_name);
                NEW.street := COALESCE(NEW.details->>'street',NEW.street);
                NEW.city := COALESCE(NEW.details->>'city',NEW.city);
                NEW.state := COALESCE(NEW.details->>'state',NEW.state,'');
                NEW.pin_code := COALESCE(NEW.details->>'pin_code',NEW.pin_code);
                NEW.country := COALESCE(NEW.details->>'country',NEW.country,'IN');
                NEW.label := COALESCE(NEW.details->>'label',NEW.label,'Saved address');
                IF NEW.details ? 'phone' THEN NEW.phone := NEW.details->>'phone'; END IF;
                NEW.is_default := COALESCE((NEW.details->>'is_default')::boolean,NEW.is_default,false);
            END IF;
            NEW.details := COALESCE(NEW.details,'{}'::jsonb) || jsonb_build_object(
                'full_name',NEW.full_name,'street',NEW.street,'city',NEW.city,'state',NEW.state,
                'pin_code',NEW.pin_code,'country',NEW.country,'label',NEW.label,'phone',NEW.phone,'is_default',NEW.is_default
            );
            RETURN NEW;
        END; $$
    """)
    _trigger(
        "CREATE TRIGGER sync_address_representations BEFORE INSERT OR UPDATE ON addresses FOR EACH ROW EXECUTE FUNCTION sync_legacy_address_columns()"
    )
    op.execute("ALTER TABLE addresses ALTER COLUMN details SET NOT NULL")


# Frozen DDL from commerce revision 0006 is appended below. No imports of live models.
COMMERCE_DDL: tuple[str, ...] = (
    "CREATE TABLE IF NOT EXISTS approvals (\n\tid UUID NOT NULL, \n\tresource_type VARCHAR(100) NOT NULL, \n\tresource_id UUID NOT NULL, \n\trequested_by VARCHAR(200) NOT NULL, \n\tdecided_by VARCHAR(200), \n\tstatus VARCHAR(20) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_approvals PRIMARY KEY (id), \n\tCONSTRAINT ck_approvals_status_allowed CHECK (status IN ('pending','approved','rejected'))\n)",
    "CREATE INDEX IF NOT EXISTS ix_approvals_resource_id ON approvals (resource_id)",
    "CREATE TABLE IF NOT EXISTS audit_ledger (\n\tid UUID NOT NULL, \n\tactor_id VARCHAR(200) NOT NULL, \n\taction VARCHAR(100) NOT NULL, \n\tresource_type VARCHAR(100) NOT NULL, \n\tresource_id UUID NOT NULL, \n\tbefore_state JSONB NOT NULL, \n\tafter_state JSONB NOT NULL, \n\tcorrelation_id VARCHAR(200) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_audit_ledger PRIMARY KEY (id)\n)",
    "CREATE INDEX IF NOT EXISTS ix_audit_ledger_resource_id ON audit_ledger (resource_id)",
    "CREATE TABLE IF NOT EXISTS customers (\n\tid UUID NOT NULL, \n\tauth_subject VARCHAR(200) NOT NULL, \n\tdisplay_name VARCHAR(200), \n\temail VARCHAR(320), \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_customers PRIMARY KEY (id), \n\tCONSTRAINT uq_customers_auth_subject UNIQUE (auth_subject)\n)",
    "CREATE TABLE IF NOT EXISTS locations (\n\tid UUID NOT NULL, \n\tname VARCHAR(200) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_locations PRIMARY KEY (id), \n\tCONSTRAINT uq_locations_name UNIQUE (name)\n)",
    "CREATE TABLE IF NOT EXISTS outbox_events (\n\tid UUID NOT NULL, \n\taggregate_type VARCHAR(100) NOT NULL, \n\taggregate_id UUID NOT NULL, \n\tevent_type VARCHAR(100) NOT NULL, \n\tpayload JSONB NOT NULL, \n\tcorrelation_id VARCHAR(200) NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\tattempts INTEGER NOT NULL, \n\tnext_attempt_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tlease_token UUID, \n\tlast_error VARCHAR(200), \n\tconsecutive_errors INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_outbox_events PRIMARY KEY (id), \n\tCONSTRAINT ck_outbox_events_status_allowed CHECK (status IN ('pending','processing','published','dead'))\n)",
    "CREATE INDEX IF NOT EXISTS ix_outbox_events_aggregate_id ON outbox_events (aggregate_id)",
    "CREATE INDEX IF NOT EXISTS ix_outbox_events_next_attempt_at ON outbox_events (next_attempt_at)",
    "CREATE TABLE IF NOT EXISTS price_books (\n\tid UUID NOT NULL, \n\tname VARCHAR(100) NOT NULL, \n\tpriority INTEGER NOT NULL, \n\tcurrency VARCHAR(3) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_price_books PRIMARY KEY (id), \n\tCONSTRAINT uq_price_books_name UNIQUE (name)\n)",
    "CREATE TABLE IF NOT EXISTS promotions (\n\tid UUID NOT NULL, \n\tname VARCHAR(200) NOT NULL, \n\tpercent_off INTEGER NOT NULL, \n\tcurrency VARCHAR(3) NOT NULL, \n\tstarts_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tends_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_promotions PRIMARY KEY (id), \n\tCONSTRAINT ck_promotions_percent_valid CHECK (percent_off > 0 AND percent_off <= 100), \n\tCONSTRAINT ck_promotions_window_valid CHECK (ends_at > starts_at)\n)",
    "CREATE TABLE IF NOT EXISTS webhook_inbox (\n\tid UUID NOT NULL, \n\tprovider VARCHAR(50) NOT NULL, \n\tprovider_event_id VARCHAR(200) NOT NULL, \n\tsignature_verified BOOLEAN NOT NULL, \n\traw_payload JSONB NOT NULL, \n\tprocessing_error VARCHAR(200), \n\tprocessed BOOLEAN NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_webhook_inbox PRIMARY KEY (id), \n\tCONSTRAINT uq_webhook_inbox_provider UNIQUE (provider, provider_event_id)\n)",
    "CREATE TABLE IF NOT EXISTS addresses (\n\tid UUID NOT NULL, \n\tcustomer_id UUID NOT NULL, \n\tdetails JSONB NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_addresses PRIMARY KEY (id), \n\tCONSTRAINT fk_addresses_customer_id_customers FOREIGN KEY(customer_id) REFERENCES customers (id)\n)",
    "CREATE INDEX IF NOT EXISTS ix_addresses_customer_id ON addresses (customer_id)",
    "CREATE TABLE IF NOT EXISTS coupons (\n\tid UUID NOT NULL, \n\tpromotion_id UUID NOT NULL, \n\tcode VARCHAR(100) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_coupons PRIMARY KEY (id), \n\tCONSTRAINT fk_coupons_promotion_id_promotions FOREIGN KEY(promotion_id) REFERENCES promotions (id), \n\tCONSTRAINT uq_coupons_code UNIQUE (code)\n)",
    "CREATE TABLE IF NOT EXISTS inventory_items (\n\tid UUID NOT NULL, \n\tvariant_id UUID NOT NULL, \n\tlocation_id UUID NOT NULL, \n\ton_hand INTEGER NOT NULL, \n\treserved INTEGER NOT NULL, \n\tsafety_stock INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_inventory_items PRIMARY KEY (id), \n\tCONSTRAINT uq_inventory_items_variant_id UNIQUE (variant_id, location_id), \n\tCONSTRAINT ck_inventory_items_stock_nonnegative CHECK (on_hand >= 0 AND reserved >= 0 AND safety_stock >= 0 AND on_hand >= reserved + safety_stock), \n\tCONSTRAINT fk_inventory_items_variant_id_variants FOREIGN KEY(variant_id) REFERENCES variants (id), \n\tCONSTRAINT fk_inventory_items_location_id_locations FOREIGN KEY(location_id) REFERENCES locations (id)\n)",
    "CREATE INDEX IF NOT EXISTS ix_inventory_items_variant_id ON inventory_items (variant_id)",
    "CREATE TABLE IF NOT EXISTS prices (\n\tid UUID NOT NULL, \n\tprice_book_id UUID NOT NULL, \n\tvariant_id UUID NOT NULL, \n\tamount_minor BIGINT NOT NULL, \n\tcurrency VARCHAR(3) NOT NULL, \n\tstarts_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tends_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_prices PRIMARY KEY (id), \n\tCONSTRAINT ck_prices_amount_nonnegative CHECK (amount_minor >= 0), \n\tCONSTRAINT ck_prices_window_valid CHECK (ends_at IS NULL OR ends_at > starts_at), \n\tCONSTRAINT fk_prices_price_book_id_price_books FOREIGN KEY(price_book_id) REFERENCES price_books (id), \n\tCONSTRAINT fk_prices_variant_id_variants FOREIGN KEY(variant_id) REFERENCES variants (id)\n)",
    "CREATE INDEX IF NOT EXISTS ix_prices_variant_id ON prices (variant_id)",
    "CREATE TABLE IF NOT EXISTS stock_movements (\n\tid UUID NOT NULL, \n\tinventory_item_id UUID NOT NULL, \n\tquantity INTEGER NOT NULL, \n\treason VARCHAR(500) NOT NULL, \n\tactor_id VARCHAR(200) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_stock_movements PRIMARY KEY (id), \n\tCONSTRAINT fk_stock_movements_inventory_item_id_inventory_items FOREIGN KEY(inventory_item_id) REFERENCES inventory_items (id)\n)",
    "CREATE INDEX IF NOT EXISTS ix_stock_movements_inventory_item_id ON stock_movements (inventory_item_id)",
    "CREATE TABLE IF NOT EXISTS fulfillments (\n\tid UUID NOT NULL, \n\torder_id UUID NOT NULL, \n\tstatus VARCHAR(30) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_fulfillments PRIMARY KEY (id), \n\tCONSTRAINT fk_fulfillments_order_id_orders FOREIGN KEY(order_id) REFERENCES orders (id)\n)",
    "CREATE INDEX IF NOT EXISTS ix_fulfillments_order_id ON fulfillments (order_id)",
    "CREATE TABLE IF NOT EXISTS inventory_reservations (\n\tid UUID NOT NULL, \n\tinventory_item_id UUID NOT NULL, \n\torder_id UUID NOT NULL, \n\tquantity INTEGER NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_inventory_reservations PRIMARY KEY (id), \n\tCONSTRAINT ck_inventory_reservations_quantity_positive CHECK (quantity > 0), \n\tCONSTRAINT ck_inventory_reservations_status_allowed CHECK (status IN ('held','committed','released','expired','consumed')), \n\tCONSTRAINT fk_inventory_reservations_inventory_item_id_inventory_items FOREIGN KEY(inventory_item_id) REFERENCES inventory_items (id), \n\tCONSTRAINT fk_inventory_reservations_order_id_orders FOREIGN KEY(order_id) REFERENCES orders (id)\n)",
    "CREATE INDEX IF NOT EXISTS ix_inventory_reservations_expires_at ON inventory_reservations (expires_at)",
    "CREATE INDEX IF NOT EXISTS ix_inventory_reservations_inventory_item_id ON inventory_reservations (inventory_item_id)",
    "CREATE INDEX IF NOT EXISTS ix_inventory_reservations_order_id ON inventory_reservations (order_id)",
    "CREATE TABLE IF NOT EXISTS order_status_history (\n\tid UUID NOT NULL, \n\torder_id UUID NOT NULL, \n\tfrom_status VARCHAR(30), \n\tto_status VARCHAR(30) NOT NULL, \n\tactor_id VARCHAR(200) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_order_status_history PRIMARY KEY (id), \n\tCONSTRAINT fk_order_status_history_order_id_orders FOREIGN KEY(order_id) REFERENCES orders (id)\n)",
    "CREATE INDEX IF NOT EXISTS ix_order_status_history_order_id ON order_status_history (order_id)",
    "CREATE TABLE IF NOT EXISTS returns (\n\tid UUID NOT NULL, \n\torder_id UUID NOT NULL, \n\tstatus VARCHAR(30) NOT NULL, \n\treason VARCHAR(1000) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_returns PRIMARY KEY (id), \n\tCONSTRAINT ck_returns_status_allowed CHECK (status IN ('requested','approved','rejected','in_transit','received','inspected','refund_pending','refunded','refund_failed')), \n\tCONSTRAINT fk_returns_order_id_orders FOREIGN KEY(order_id) REFERENCES orders (id)\n)",
    "CREATE INDEX IF NOT EXISTS ix_returns_order_id ON returns (order_id)",
    "CREATE TABLE IF NOT EXISTS support_cases (\n\tid UUID NOT NULL, \n\tcustomer_id UUID NOT NULL, \n\torder_id UUID, \n\tsubject VARCHAR(300) NOT NULL, \n\tstatus VARCHAR(30) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_support_cases PRIMARY KEY (id), \n\tCONSTRAINT fk_support_cases_customer_id_customers FOREIGN KEY(customer_id) REFERENCES customers (id), \n\tCONSTRAINT fk_support_cases_order_id_orders FOREIGN KEY(order_id) REFERENCES orders (id)\n)",
    "CREATE INDEX IF NOT EXISTS ix_support_cases_customer_id ON support_cases (customer_id)",
    "CREATE TABLE IF NOT EXISTS case_messages (\n\tid UUID NOT NULL, \n\tcase_id UUID NOT NULL, \n\tactor_id VARCHAR(200) NOT NULL, \n\tbody TEXT, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_case_messages PRIMARY KEY (id), \n\tCONSTRAINT fk_case_messages_case_id_support_cases FOREIGN KEY(case_id) REFERENCES support_cases (id)\n)",
    "CREATE INDEX IF NOT EXISTS ix_case_messages_case_id ON case_messages (case_id)",
    "CREATE TABLE IF NOT EXISTS payment_transactions (\n\tid UUID NOT NULL, \n\tpayment_attempt_id UUID NOT NULL, \n\tprovider_event_id VARCHAR(200) NOT NULL, \n\tkind VARCHAR(30) NOT NULL, \n\tamount_minor BIGINT NOT NULL, \n\tcurrency VARCHAR(3) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_payment_transactions PRIMARY KEY (id), \n\tCONSTRAINT fk_payment_transactions_payment_attempt_id_payment_attempts FOREIGN KEY(payment_attempt_id) REFERENCES payment_attempts (id), \n\tCONSTRAINT uq_payment_transactions_provider_event_id UNIQUE (provider_event_id)\n)",
    "CREATE INDEX IF NOT EXISTS ix_payment_transactions_payment_attempt_id ON payment_transactions (payment_attempt_id)",
    "CREATE TABLE IF NOT EXISTS refunds (\n\tid UUID NOT NULL, \n\tpayment_attempt_id UUID NOT NULL, \n\treturn_id UUID, \n\tapproval_id UUID, \n\tamount_minor BIGINT NOT NULL, \n\tcurrency VARCHAR(3) NOT NULL, \n\tstatus VARCHAR(30) NOT NULL, \n\trequested_by VARCHAR(200) NOT NULL, \n\tprovider_reference VARCHAR(200), \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_refunds PRIMARY KEY (id), \n\tCONSTRAINT ck_refunds_amount_positive CHECK (amount_minor > 0), \n\tCONSTRAINT ck_refunds_status_allowed CHECK (status IN ('awaiting_approval','refund_pending','refunded','refund_failed','rejected')), \n\tCONSTRAINT fk_refunds_payment_attempt_id_payment_attempts FOREIGN KEY(payment_attempt_id) REFERENCES payment_attempts (id), \n\tCONSTRAINT fk_refunds_return_id_returns FOREIGN KEY(return_id) REFERENCES returns (id), \n\tCONSTRAINT fk_refunds_approval_id_approvals FOREIGN KEY(approval_id) REFERENCES approvals (id)\n)",
    "CREATE INDEX IF NOT EXISTS ix_refunds_payment_attempt_id ON refunds (payment_attempt_id)",
    "CREATE TABLE IF NOT EXISTS return_items (\n\tid UUID NOT NULL, \n\treturn_id UUID NOT NULL, \n\torder_item_id UUID NOT NULL, \n\tquantity INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_return_items PRIMARY KEY (id), \n\tCONSTRAINT ck_return_items_quantity_positive CHECK (quantity > 0), \n\tCONSTRAINT fk_return_items_return_id_returns FOREIGN KEY(return_id) REFERENCES returns (id), \n\tCONSTRAINT fk_return_items_order_item_id_order_items FOREIGN KEY(order_item_id) REFERENCES order_items (id)\n)",
    "CREATE INDEX IF NOT EXISTS ix_return_items_return_id ON return_items (return_id)",
    "CREATE TABLE IF NOT EXISTS shipments (\n\tid UUID NOT NULL, \n\tfulfillment_id UUID NOT NULL, \n\tcarrier VARCHAR(100) NOT NULL, \n\ttracking_number VARCHAR(200) NOT NULL, \n\tstatus VARCHAR(30) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_shipments PRIMARY KEY (id), \n\tCONSTRAINT fk_shipments_fulfillment_id_fulfillments FOREIGN KEY(fulfillment_id) REFERENCES fulfillments (id)\n)",
    "CREATE INDEX IF NOT EXISTS ix_shipments_fulfillment_id ON shipments (fulfillment_id)",
    "CREATE TABLE IF NOT EXISTS shipment_items (\n\tid UUID NOT NULL, \n\tshipment_id UUID NOT NULL, \n\torder_item_id UUID NOT NULL, \n\tquantity INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_shipment_items PRIMARY KEY (id), \n\tCONSTRAINT ck_shipment_items_quantity_positive CHECK (quantity > 0), \n\tCONSTRAINT fk_shipment_items_shipment_id_shipments FOREIGN KEY(shipment_id) REFERENCES shipments (id), \n\tCONSTRAINT fk_shipment_items_order_item_id_order_items FOREIGN KEY(order_item_id) REFERENCES order_items (id)\n)",
    "CREATE INDEX IF NOT EXISTS ix_shipment_items_shipment_id ON shipment_items (shipment_id)",
    "ALTER TABLE carts ADD COLUMN IF NOT EXISTS customer_id UUID REFERENCES customers(id)",
    "CREATE INDEX IF NOT EXISTS ix_carts_customer_id ON carts(customer_id)",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS customer_id UUID REFERENCES customers(id)",
    "CREATE INDEX IF NOT EXISTS ix_orders_customer_id ON orders(customer_id)",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS discount_minor BIGINT NOT NULL DEFAULT 0",
    "ALTER TABLE order_items ADD COLUMN IF NOT EXISTS line_discount_minor BIGINT NOT NULL DEFAULT 0",
    "ALTER TABLE order_items ADD COLUMN IF NOT EXISTS line_tax_minor BIGINT NOT NULL DEFAULT 0",
    "ALTER TABLE order_items ADD COLUMN IF NOT EXISTS promotion_id UUID REFERENCES promotions(id)",
    "ALTER TABLE consent_records ADD COLUMN IF NOT EXISTS customer_id UUID REFERENCES customers(id)",
    "CREATE INDEX IF NOT EXISTS ix_consent_records_customer_id ON consent_records(customer_id)",
    "ALTER TABLE consent_records ADD COLUMN IF NOT EXISTS notice_version VARCHAR(100)",
    "ALTER TABLE idempotency_keys ADD COLUMN IF NOT EXISTS response_body JSONB",
    "ALTER TABLE idempotency_keys ADD COLUMN IF NOT EXISTS response_status INTEGER",
    "ALTER TABLE idempotency_keys ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ",
    "ALTER TABLE payment_attempts ADD COLUMN IF NOT EXISTS captured_amount_minor BIGINT NOT NULL DEFAULT 0",
    "ALTER TABLE payment_attempts ADD COLUMN IF NOT EXISTS refunded_amount_minor BIGINT NOT NULL DEFAULT 0",
    "ALTER TABLE payment_attempts ADD CONSTRAINT ck_payment_attempts_amounts_valid CHECK (captured_amount_minor >= 0 AND refunded_amount_minor >= 0 AND refunded_amount_minor <= captured_amount_minor AND captured_amount_minor <= amount_minor)",
    "ALTER TABLE orders DROP CONSTRAINT IF EXISTS ck_orders_status_allowed",
    "ALTER TABLE orders ADD CONSTRAINT ck_orders_status_allowed CHECK (status IN ('pending_payment','payment_failed','expired','confirmed','allocated','partially_fulfilled','fulfilled','delivered','cancelled'))",
    "ALTER TABLE payment_attempts DROP CONSTRAINT IF EXISTS ck_payment_attempts_status_allowed",
    "ALTER TABLE payment_attempts ADD CONSTRAINT ck_payment_attempts_status_allowed CHECK (status IN ('initiated','pending','requires_action','authorized','captured','failed','expired','voided','partially_refunded','refunded'))",
    "CREATE INDEX IF NOT EXISTS ix_outbox_claim ON outbox_events(status,next_attempt_at) WHERE status IN ('pending','processing')",
    "CREATE INDEX IF NOT EXISTS ix_reservation_expiry ON inventory_reservations(status,expires_at) WHERE status = 'held'",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_customer_open_cart ON carts(customer_id) WHERE status = 'open' AND customer_id IS NOT NULL",
    "CREATE OR REPLACE FUNCTION reject_commerce_history_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'commerce history is append-only'; END; $$",
    "CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON audit_ledger FOR EACH ROW EXECUTE FUNCTION reject_commerce_history_mutation()",
    "CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON consent_records FOR EACH ROW EXECUTE FUNCTION reject_commerce_history_mutation()",
    "CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON stock_movements FOR EACH ROW EXECUTE FUNCTION reject_commerce_history_mutation()",
    "CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON order_status_history FOR EACH ROW EXECUTE FUNCTION reject_commerce_history_mutation()",
    "CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON order_items FOR EACH ROW EXECUTE FUNCTION reject_commerce_history_mutation()",
    "CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON payment_transactions FOR EACH ROW EXECUTE FUNCTION reject_commerce_history_mutation()",
    "CREATE OR REPLACE FUNCTION protect_order_snapshot() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF (to_jsonb(NEW) - ARRAY['status','updated_at','customer_id']) IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['status','updated_at','customer_id']) THEN RAISE EXCEPTION 'order commercial snapshot is immutable'; END IF; RETURN NEW; END; $$",
    "CREATE TRIGGER immutable_order_snapshot BEFORE UPDATE ON orders FOR EACH ROW EXECUTE FUNCTION protect_order_snapshot()",
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    for statement in COMMERCE_DDL:
        stripped = statement.strip()
        if stripped.startswith("CREATE TRIGGER"):
            _trigger(stripped)
        elif "ADD CONSTRAINT" in stripped:
            words = stripped.split()
            table, name = words[2], words[words.index("CONSTRAINT") + 1]
            if not _constraint_exists(table, name):
                op.execute(statement)
        else:
            op.execute(statement)
    _legacy_customer_columns()
    _legacy_address_columns()


def downgrade() -> None:
    raise RuntimeError(
        "Reconciliation preserves commerce history; use a reviewed forward migration"
    )
