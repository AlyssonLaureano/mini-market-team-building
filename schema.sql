
CREATE TABLE groups (
    group_id INTEGER PRIMARY KEY,
    group_name TEXT NOT NULL,
    initial_balance REAL NOT NULL DEFAULT 0,
    current_balance REAL NOT NULL DEFAULT 0
);

CREATE TABLE products (
    product_id INTEGER PRIMARY KEY,
    product_name TEXT NOT NULL,
    price REAL NOT NULL DEFAULT 0,
    stock INTEGER NOT NULL DEFAULT 0,
    initial_stock INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE purchases (
    purchase_id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL,
    date_time TEXT NOT NULL,
    total REAL NOT NULL,
    balance_before REAL NOT NULL,
    balance_after REAL NOT NULL,
    FOREIGN KEY(group_id) REFERENCES groups(group_id)
);

CREATE TABLE purchase_items (
    purchase_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    subtotal REAL NOT NULL,
    FOREIGN KEY(purchase_id) REFERENCES purchases(purchase_id),
    FOREIGN KEY(product_id) REFERENCES products(product_id)
);
