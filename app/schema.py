SCHEMA_DESCRIPTION = """
You may query ONLY the following tables (read-only product catalog data):

TABLE categories (
  id integer PRIMARY KEY,
  name varchar,
  slug varchar UNIQUE,
  image_url text NULL,
  created_at timestamptz
)

TABLE products (
  id integer PRIMARY KEY,
  name varchar,
  slug varchar UNIQUE,
  description text NULL,
  price numeric,
  sale_price numeric NULL,      -- discounted price, NULL if not on sale
  category_id integer NULL REFERENCES categories(id),
  stock integer,                -- units available; 0 means out of stock
  is_featured boolean,
  created_at timestamptz
)

TABLE product_images (
  id integer PRIMARY KEY,
  product_id integer REFERENCES products(id),
  image_url text,
  display_order integer
)

Rules:
- Only SELECT statements are allowed. Never write INSERT/UPDATE/DELETE/DDL.
- Only reference the three tables above. No other tables exist for you.
- Use sale_price when present as the effective price, otherwise price.
- Always add a reasonable LIMIT (<=20) unless the user asks for a count/aggregate.
"""

ALLOWED_TABLES = {"products", "categories", "product_images"}
