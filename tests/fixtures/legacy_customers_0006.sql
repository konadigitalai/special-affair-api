-- Earlier development-only customer migration, replayed in disposable test databases.
CREATE TABLE customers (
    id UUID PRIMARY KEY, auth0_sub VARCHAR(200) NOT NULL UNIQUE,
    email VARCHAR(320), email_verified BOOLEAN NOT NULL DEFAULT false,
    name VARCHAR(200), phone VARCHAR(30), preferences JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE addresses (
    id UUID PRIMARY KEY, customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    label VARCHAR(100) NOT NULL, full_name VARCHAR(200) NOT NULL, street VARCHAR(500) NOT NULL,
    city VARCHAR(150) NOT NULL, state VARCHAR(150) NOT NULL, pin_code VARCHAR(20) NOT NULL,
    country VARCHAR(10) NOT NULL, phone VARCHAR(30), is_default BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE carts ADD COLUMN customer_id UUID REFERENCES customers(id) ON DELETE SET NULL;
ALTER TABLE orders ADD COLUMN customer_id UUID REFERENCES customers(id) ON DELETE SET NULL;
