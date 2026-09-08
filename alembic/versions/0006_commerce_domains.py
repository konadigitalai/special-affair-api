"""Expand commerce domains and protect financial history.

Deploy this migration BEFORE deploying the new application and worker.
Legacy columns remain; new state constraints are supersets of old values.
Irreversible: dropping financial/audit/consent history is unsafe. Roll back the
application only; use a forward corrective migration for schema defects.
On populated deployments run the capture backfill in a separate preflight job
and review lock duration before applying constraint/trigger changes.
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        "\nCREATE TABLE approvals (\n\tid UUID NOT NULL, \n\tresource_type VARCHAR(100) NOT NULL, \n\tresource_id UUID NOT NULL, \n\trequested_by VARCHAR(200) NOT NULL, \n\tdecided_by VARCHAR(200), \n\tstatus VARCHAR(20) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_approvals PRIMARY KEY (id), \n\tCONSTRAINT ck_approvals_status_allowed CHECK (status IN ('pending','approved','rejected'))\n)\n\n"
    )
    op.execute("CREATE INDEX ix_approvals_resource_id ON approvals (resource_id)")
    op.execute(
        "\nCREATE TABLE audit_ledger (\n\tid UUID NOT NULL, \n\tactor_id VARCHAR(200) NOT NULL, \n\taction VARCHAR(100) NOT NULL, \n\tresource_type VARCHAR(100) NOT NULL, \n\tresource_id UUID NOT NULL, \n\tbefore_state JSONB NOT NULL, \n\tafter_state JSONB NOT NULL, \n\tcorrelation_id VARCHAR(200) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_audit_ledger PRIMARY KEY (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_audit_ledger_resource_id ON audit_ledger (resource_id)")
    op.execute(
        "\nCREATE TABLE customers (\n\tid UUID NOT NULL, \n\tauth_subject VARCHAR(200) NOT NULL, \n\tdisplay_name VARCHAR(200), \n\temail VARCHAR(320), \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_customers PRIMARY KEY (id), \n\tCONSTRAINT uq_customers_auth_subject UNIQUE (auth_subject)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE locations (\n\tid UUID NOT NULL, \n\tname VARCHAR(200) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_locations PRIMARY KEY (id), \n\tCONSTRAINT uq_locations_name UNIQUE (name)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE outbox_events (\n\tid UUID NOT NULL, \n\taggregate_type VARCHAR(100) NOT NULL, \n\taggregate_id UUID NOT NULL, \n\tevent_type VARCHAR(100) NOT NULL, \n\tpayload JSONB NOT NULL, \n\tcorrelation_id VARCHAR(200) NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\tattempts INTEGER NOT NULL, \n\tnext_attempt_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tlease_token UUID, \n\tlast_error VARCHAR(200), \n\tconsecutive_errors INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_outbox_events PRIMARY KEY (id), \n\tCONSTRAINT ck_outbox_events_status_allowed CHECK (status IN ('pending','processing','published','dead'))\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_outbox_events_aggregate_id ON outbox_events (aggregate_id)"
    )
    op.execute(
        "CREATE INDEX ix_outbox_events_next_attempt_at ON outbox_events (next_attempt_at)"
    )
    op.execute(
        "\nCREATE TABLE price_books (\n\tid UUID NOT NULL, \n\tname VARCHAR(100) NOT NULL, \n\tpriority INTEGER NOT NULL, \n\tcurrency VARCHAR(3) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_price_books PRIMARY KEY (id), \n\tCONSTRAINT uq_price_books_name UNIQUE (name)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE promotions (\n\tid UUID NOT NULL, \n\tname VARCHAR(200) NOT NULL, \n\tpercent_off INTEGER NOT NULL, \n\tcurrency VARCHAR(3) NOT NULL, \n\tstarts_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tends_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_promotions PRIMARY KEY (id), \n\tCONSTRAINT ck_promotions_percent_valid CHECK (percent_off > 0 AND percent_off <= 100), \n\tCONSTRAINT ck_promotions_window_valid CHECK (ends_at > starts_at)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE webhook_inbox (\n\tid UUID NOT NULL, \n\tprovider VARCHAR(50) NOT NULL, \n\tprovider_event_id VARCHAR(200) NOT NULL, \n\tsignature_verified BOOLEAN NOT NULL, \n\traw_payload JSONB NOT NULL, \n\tprocessing_error VARCHAR(200), \n\tprocessed BOOLEAN NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_webhook_inbox PRIMARY KEY (id), \n\tCONSTRAINT uq_webhook_inbox_provider UNIQUE (provider, provider_event_id)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE addresses (\n\tid UUID NOT NULL, \n\tcustomer_id UUID NOT NULL, \n\tdetails JSONB NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_addresses PRIMARY KEY (id), \n\tCONSTRAINT fk_addresses_customer_id_customers FOREIGN KEY(customer_id) REFERENCES customers (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_addresses_customer_id ON addresses (customer_id)")
    op.execute(
        "\nCREATE TABLE coupons (\n\tid UUID NOT NULL, \n\tpromotion_id UUID NOT NULL, \n\tcode VARCHAR(100) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_coupons PRIMARY KEY (id), \n\tCONSTRAINT fk_coupons_promotion_id_promotions FOREIGN KEY(promotion_id) REFERENCES promotions (id), \n\tCONSTRAINT uq_coupons_code UNIQUE (code)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE inventory_items (\n\tid UUID NOT NULL, \n\tvariant_id UUID NOT NULL, \n\tlocation_id UUID NOT NULL, \n\ton_hand INTEGER NOT NULL, \n\treserved INTEGER NOT NULL, \n\tsafety_stock INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_inventory_items PRIMARY KEY (id), \n\tCONSTRAINT uq_inventory_items_variant_id UNIQUE (variant_id, location_id), \n\tCONSTRAINT ck_inventory_items_stock_nonnegative CHECK (on_hand >= 0 AND reserved >= 0 AND safety_stock >= 0 AND on_hand >= reserved + safety_stock), \n\tCONSTRAINT fk_inventory_items_variant_id_variants FOREIGN KEY(variant_id) REFERENCES variants (id), \n\tCONSTRAINT fk_inventory_items_location_id_locations FOREIGN KEY(location_id) REFERENCES locations (id)\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_inventory_items_variant_id ON inventory_items (variant_id)"
    )
    op.execute(
        "\nCREATE TABLE prices (\n\tid UUID NOT NULL, \n\tprice_book_id UUID NOT NULL, \n\tvariant_id UUID NOT NULL, \n\tamount_minor BIGINT NOT NULL, \n\tcurrency VARCHAR(3) NOT NULL, \n\tstarts_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tends_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_prices PRIMARY KEY (id), \n\tCONSTRAINT ck_prices_amount_nonnegative CHECK (amount_minor >= 0), \n\tCONSTRAINT ck_prices_window_valid CHECK (ends_at IS NULL OR ends_at > starts_at), \n\tCONSTRAINT fk_prices_price_book_id_price_books FOREIGN KEY(price_book_id) REFERENCES price_books (id), \n\tCONSTRAINT fk_prices_variant_id_variants FOREIGN KEY(variant_id) REFERENCES variants (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_prices_variant_id ON prices (variant_id)")
    op.execute(
        "\nCREATE TABLE stock_movements (\n\tid UUID NOT NULL, \n\tinventory_item_id UUID NOT NULL, \n\tquantity INTEGER NOT NULL, \n\treason VARCHAR(500) NOT NULL, \n\tactor_id VARCHAR(200) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_stock_movements PRIMARY KEY (id), \n\tCONSTRAINT fk_stock_movements_inventory_item_id_inventory_items FOREIGN KEY(inventory_item_id) REFERENCES inventory_items (id)\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_stock_movements_inventory_item_id ON stock_movements (inventory_item_id)"
    )
    op.execute(
        "\nCREATE TABLE fulfillments (\n\tid UUID NOT NULL, \n\torder_id UUID NOT NULL, \n\tstatus VARCHAR(30) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_fulfillments PRIMARY KEY (id), \n\tCONSTRAINT fk_fulfillments_order_id_orders FOREIGN KEY(order_id) REFERENCES orders (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_fulfillments_order_id ON fulfillments (order_id)")
    op.execute(
        "\nCREATE TABLE inventory_reservations (\n\tid UUID NOT NULL, \n\tinventory_item_id UUID NOT NULL, \n\torder_id UUID NOT NULL, \n\tquantity INTEGER NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_inventory_reservations PRIMARY KEY (id), \n\tCONSTRAINT ck_inventory_reservations_quantity_positive CHECK (quantity > 0), \n\tCONSTRAINT ck_inventory_reservations_status_allowed CHECK (status IN ('held','committed','released','expired','consumed')), \n\tCONSTRAINT fk_inventory_reservations_inventory_item_id_inventory_items FOREIGN KEY(inventory_item_id) REFERENCES inventory_items (id), \n\tCONSTRAINT fk_inventory_reservations_order_id_orders FOREIGN KEY(order_id) REFERENCES orders (id)\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_inventory_reservations_expires_at ON inventory_reservations (expires_at)"
    )
    op.execute(
        "CREATE INDEX ix_inventory_reservations_inventory_item_id ON inventory_reservations (inventory_item_id)"
    )
    op.execute(
        "CREATE INDEX ix_inventory_reservations_order_id ON inventory_reservations (order_id)"
    )
    op.execute(
        "\nCREATE TABLE order_status_history (\n\tid UUID NOT NULL, \n\torder_id UUID NOT NULL, \n\tfrom_status VARCHAR(30), \n\tto_status VARCHAR(30) NOT NULL, \n\tactor_id VARCHAR(200) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_order_status_history PRIMARY KEY (id), \n\tCONSTRAINT fk_order_status_history_order_id_orders FOREIGN KEY(order_id) REFERENCES orders (id)\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_order_status_history_order_id ON order_status_history (order_id)"
    )
    op.execute(
        "\nCREATE TABLE returns (\n\tid UUID NOT NULL, \n\torder_id UUID NOT NULL, \n\tstatus VARCHAR(30) NOT NULL, \n\treason VARCHAR(1000) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_returns PRIMARY KEY (id), \n\tCONSTRAINT ck_returns_status_allowed CHECK (status IN ('requested','approved','rejected','in_transit','received','inspected','refund_pending','refunded','refund_failed')), \n\tCONSTRAINT fk_returns_order_id_orders FOREIGN KEY(order_id) REFERENCES orders (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_returns_order_id ON returns (order_id)")
    op.execute(
        "\nCREATE TABLE support_cases (\n\tid UUID NOT NULL, \n\tcustomer_id UUID NOT NULL, \n\torder_id UUID, \n\tsubject VARCHAR(300) NOT NULL, \n\tstatus VARCHAR(30) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_support_cases PRIMARY KEY (id), \n\tCONSTRAINT fk_support_cases_customer_id_customers FOREIGN KEY(customer_id) REFERENCES customers (id), \n\tCONSTRAINT fk_support_cases_order_id_orders FOREIGN KEY(order_id) REFERENCES orders (id)\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_support_cases_customer_id ON support_cases (customer_id)"
    )
    op.execute(
        "\nCREATE TABLE case_messages (\n\tid UUID NOT NULL, \n\tcase_id UUID NOT NULL, \n\tactor_id VARCHAR(200) NOT NULL, \n\tbody TEXT, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_case_messages PRIMARY KEY (id), \n\tCONSTRAINT fk_case_messages_case_id_support_cases FOREIGN KEY(case_id) REFERENCES support_cases (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_case_messages_case_id ON case_messages (case_id)")
    op.execute(
        "\nCREATE TABLE payment_transactions (\n\tid UUID NOT NULL, \n\tpayment_attempt_id UUID NOT NULL, \n\tprovider_event_id VARCHAR(200) NOT NULL, \n\tkind VARCHAR(30) NOT NULL, \n\tamount_minor BIGINT NOT NULL, \n\tcurrency VARCHAR(3) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_payment_transactions PRIMARY KEY (id), \n\tCONSTRAINT fk_payment_transactions_payment_attempt_id_payment_attempts FOREIGN KEY(payment_attempt_id) REFERENCES payment_attempts (id), \n\tCONSTRAINT uq_payment_transactions_provider_event_id UNIQUE (provider_event_id)\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_payment_transactions_payment_attempt_id ON payment_transactions (payment_attempt_id)"
    )
    op.execute(
        "\nCREATE TABLE refunds (\n\tid UUID NOT NULL, \n\tpayment_attempt_id UUID NOT NULL, \n\treturn_id UUID, \n\tapproval_id UUID, \n\tamount_minor BIGINT NOT NULL, \n\tcurrency VARCHAR(3) NOT NULL, \n\tstatus VARCHAR(30) NOT NULL, \n\trequested_by VARCHAR(200) NOT NULL, \n\tprovider_reference VARCHAR(200), \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_refunds PRIMARY KEY (id), \n\tCONSTRAINT ck_refunds_amount_positive CHECK (amount_minor > 0), \n\tCONSTRAINT ck_refunds_status_allowed CHECK (status IN ('awaiting_approval','refund_pending','refunded','refund_failed','rejected')), \n\tCONSTRAINT fk_refunds_payment_attempt_id_payment_attempts FOREIGN KEY(payment_attempt_id) REFERENCES payment_attempts (id), \n\tCONSTRAINT fk_refunds_return_id_returns FOREIGN KEY(return_id) REFERENCES returns (id), \n\tCONSTRAINT fk_refunds_approval_id_approvals FOREIGN KEY(approval_id) REFERENCES approvals (id)\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_refunds_payment_attempt_id ON refunds (payment_attempt_id)"
    )
    op.execute(
        "\nCREATE TABLE return_items (\n\tid UUID NOT NULL, \n\treturn_id UUID NOT NULL, \n\torder_item_id UUID NOT NULL, \n\tquantity INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_return_items PRIMARY KEY (id), \n\tCONSTRAINT ck_return_items_quantity_positive CHECK (quantity > 0), \n\tCONSTRAINT fk_return_items_return_id_returns FOREIGN KEY(return_id) REFERENCES returns (id), \n\tCONSTRAINT fk_return_items_order_item_id_order_items FOREIGN KEY(order_item_id) REFERENCES order_items (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_return_items_return_id ON return_items (return_id)")
    op.execute(
        "\nCREATE TABLE shipments (\n\tid UUID NOT NULL, \n\tfulfillment_id UUID NOT NULL, \n\tcarrier VARCHAR(100) NOT NULL, \n\ttracking_number VARCHAR(200) NOT NULL, \n\tstatus VARCHAR(30) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_shipments PRIMARY KEY (id), \n\tCONSTRAINT fk_shipments_fulfillment_id_fulfillments FOREIGN KEY(fulfillment_id) REFERENCES fulfillments (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_shipments_fulfillment_id ON shipments (fulfillment_id)")
    op.execute(
        "\nCREATE TABLE shipment_items (\n\tid UUID NOT NULL, \n\tshipment_id UUID NOT NULL, \n\torder_item_id UUID NOT NULL, \n\tquantity INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_shipment_items PRIMARY KEY (id), \n\tCONSTRAINT ck_shipment_items_quantity_positive CHECK (quantity > 0), \n\tCONSTRAINT fk_shipment_items_shipment_id_shipments FOREIGN KEY(shipment_id) REFERENCES shipments (id), \n\tCONSTRAINT fk_shipment_items_order_item_id_order_items FOREIGN KEY(order_item_id) REFERENCES order_items (id)\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_shipment_items_shipment_id ON shipment_items (shipment_id)"
    )
    op.execute("ALTER TABLE carts ADD COLUMN customer_id UUID REFERENCES customers(id)")
    op.execute("CREATE INDEX ix_carts_customer_id ON carts(customer_id)")
    op.execute(
        "ALTER TABLE orders ADD COLUMN customer_id UUID REFERENCES customers(id)"
    )
    op.execute("CREATE INDEX ix_orders_customer_id ON orders(customer_id)")
    op.execute("ALTER TABLE orders ADD COLUMN discount_minor BIGINT NOT NULL DEFAULT 0")
    op.execute(
        "ALTER TABLE order_items ADD COLUMN line_discount_minor BIGINT NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE order_items ADD COLUMN line_tax_minor BIGINT NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE order_items ADD COLUMN promotion_id UUID REFERENCES promotions(id)"
    )
    op.execute(
        "ALTER TABLE consent_records ADD COLUMN customer_id UUID REFERENCES customers(id)"
    )
    op.execute(
        "CREATE INDEX ix_consent_records_customer_id ON consent_records(customer_id)"
    )
    op.execute("ALTER TABLE consent_records ADD COLUMN notice_version VARCHAR(100)")
    op.execute("ALTER TABLE idempotency_keys ADD COLUMN response_body JSONB")
    op.execute("ALTER TABLE idempotency_keys ADD COLUMN response_status INTEGER")
    op.execute("ALTER TABLE idempotency_keys ADD COLUMN expires_at TIMESTAMPTZ")
    op.execute(
        "ALTER TABLE payment_attempts ADD COLUMN captured_amount_minor BIGINT NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE payment_attempts ADD COLUMN refunded_amount_minor BIGINT NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE payment_attempts ADD CONSTRAINT ck_payment_attempts_amounts_valid CHECK (captured_amount_minor >= 0 AND refunded_amount_minor >= 0 AND refunded_amount_minor <= captured_amount_minor AND captured_amount_minor <= amount_minor)"
    )
    op.execute("ALTER TABLE orders DROP CONSTRAINT ck_orders_status_allowed")
    op.execute(
        "ALTER TABLE orders ADD CONSTRAINT ck_orders_status_allowed CHECK (status IN ('pending_payment','payment_failed','expired','confirmed','allocated','partially_fulfilled','fulfilled','delivered','cancelled'))"
    )
    op.execute(
        "ALTER TABLE payment_attempts DROP CONSTRAINT ck_payment_attempts_status_allowed"
    )
    op.execute(
        "ALTER TABLE payment_attempts ADD CONSTRAINT ck_payment_attempts_status_allowed CHECK (status IN ('initiated','pending','requires_action','authorized','captured','failed','expired','voided','partially_refunded','refunded'))"
    )
    op.execute(
        "CREATE INDEX ix_outbox_claim ON outbox_events(status,next_attempt_at) WHERE status IN ('pending','processing')"
    )
    op.execute(
        "CREATE INDEX ix_reservation_expiry ON inventory_reservations(status,expires_at) WHERE status = 'held'"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_customer_open_cart ON carts(customer_id) WHERE status = 'open' AND customer_id IS NOT NULL"
    )
    op.execute(
        "CREATE FUNCTION reject_commerce_history_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'commerce history is append-only'; END; $$"
    )
    op.execute(
        "CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON audit_ledger FOR EACH ROW EXECUTE FUNCTION reject_commerce_history_mutation()"
    )
    op.execute(
        "CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON consent_records FOR EACH ROW EXECUTE FUNCTION reject_commerce_history_mutation()"
    )
    op.execute(
        "CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON stock_movements FOR EACH ROW EXECUTE FUNCTION reject_commerce_history_mutation()"
    )
    op.execute(
        "CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON order_status_history FOR EACH ROW EXECUTE FUNCTION reject_commerce_history_mutation()"
    )
    op.execute(
        "CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON order_items FOR EACH ROW EXECUTE FUNCTION reject_commerce_history_mutation()"
    )
    op.execute(
        "CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON payment_transactions FOR EACH ROW EXECUTE FUNCTION reject_commerce_history_mutation()"
    )
    op.execute(
        "CREATE FUNCTION protect_order_snapshot() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF (to_jsonb(NEW) - ARRAY['status','updated_at','customer_id']) IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['status','updated_at','customer_id']) THEN RAISE EXCEPTION 'order commercial snapshot is immutable'; END IF; RETURN NEW; END; $$"
    )
    op.execute(
        "CREATE TRIGGER immutable_order_snapshot BEFORE UPDATE ON orders FOR EACH ROW EXECUTE FUNCTION protect_order_snapshot()"
    )


def downgrade() -> None:
    raise RuntimeError(
        "Irreversible financial history expansion; use forward migration. See docs/architecture-review.md"
    )
