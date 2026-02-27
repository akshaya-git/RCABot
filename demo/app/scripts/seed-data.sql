-- =============================================================================
-- Demo Inventory Database Seed Data
-- Run this script after the database is created to populate sample data
-- =============================================================================

-- Create products table
CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    category VARCHAR(100) NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create index on category for faster searches
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);

-- Clear existing data
TRUNCATE TABLE products RESTART IDENTITY;

-- Insert sample products
INSERT INTO products (name, category, price, quantity, description) VALUES
-- Electronics
('MacBook Pro 14"', 'Electronics', 1999.99, 25, 'Apple MacBook Pro with M3 chip, 16GB RAM, 512GB SSD'),
('iPhone 15 Pro', 'Electronics', 1099.00, 150, 'Apple iPhone 15 Pro, 256GB, Titanium Black'),
('Samsung Galaxy S24', 'Electronics', 899.99, 80, 'Samsung Galaxy S24 Ultra, 256GB, Phantom Black'),
('Sony WH-1000XM5', 'Electronics', 349.99, 45, 'Sony wireless noise-canceling headphones'),
('iPad Air', 'Electronics', 599.00, 60, 'Apple iPad Air 5th Gen, 64GB, Space Gray'),
('Dell XPS 15', 'Electronics', 1499.00, 30, 'Dell XPS 15, Intel i7, 16GB RAM, 512GB SSD'),
('AirPods Pro 2', 'Electronics', 249.99, 200, 'Apple AirPods Pro 2nd generation with USB-C'),
('Nintendo Switch OLED', 'Electronics', 349.99, 40, 'Nintendo Switch OLED Model, White'),

-- Clothing
('Levi''s 501 Jeans', 'Clothing', 79.99, 120, 'Classic fit straight leg jeans, multiple sizes'),
('Nike Air Max 90', 'Clothing', 129.99, 85, 'Nike Air Max 90 sneakers, various colors'),
('Patagonia Down Jacket', 'Clothing', 279.00, 35, 'Recycled down insulated jacket'),
('North Face Backpack', 'Clothing', 89.99, 55, 'Borealis backpack, 28L capacity'),
('Ray-Ban Aviator', 'Clothing', 169.00, 70, 'Classic aviator sunglasses, gold frame'),
('Adidas Ultraboost', 'Clothing', 189.99, 65, 'Running shoes with Boost technology'),

-- Home & Kitchen
('Instant Pot Duo', 'Home & Kitchen', 89.99, 90, '7-in-1 electric pressure cooker, 6 quart'),
('Dyson V15 Detect', 'Home & Kitchen', 749.99, 20, 'Cordless vacuum with laser dust detection'),
('KitchenAid Mixer', 'Home & Kitchen', 379.99, 15, 'Artisan stand mixer, 5 quart, Empire Red'),
('Nespresso Vertuo', 'Home & Kitchen', 199.00, 50, 'Coffee and espresso machine with milk frother'),
('Le Creuset Dutch Oven', 'Home & Kitchen', 369.99, 25, 'Enameled cast iron, 5.5 quart, Flame'),
('Vitamix Blender', 'Home & Kitchen', 549.99, 18, 'Professional-grade blender, 64oz container'),

-- Books
('The Pragmatic Programmer', 'Books', 49.99, 100, 'Your journey to mastery, 20th Anniversary Edition'),
('Clean Code', 'Books', 44.99, 85, 'A handbook of agile software craftsmanship'),
('System Design Interview', 'Books', 39.99, 75, 'An insider''s guide, Volume 1'),
('Designing Data-Intensive Apps', 'Books', 54.99, 60, 'The big ideas behind reliable systems'),

-- Sports & Outdoors
('Yeti Cooler', 'Sports & Outdoors', 299.99, 30, 'Tundra 45 hard cooler, Tan'),
('Garmin Fenix 7', 'Sports & Outdoors', 699.99, 22, 'GPS multisport smartwatch'),
('Hydroflask 32oz', 'Sports & Outdoors', 44.95, 150, 'Wide mouth water bottle with flex cap'),
('Coleman Tent', 'Sports & Outdoors', 159.99, 40, '4-person dome tent with screen room'),
('Osprey Backpack', 'Sports & Outdoors', 199.99, 35, 'Atmos AG 65L hiking backpack'),

-- Low stock items (for demo alerts)
('Limited Edition Watch', 'Electronics', 2999.99, 3, 'Collector''s edition smartwatch'),
('Vintage Vinyl Record', 'Entertainment', 199.99, 5, 'Rare 1st pressing, mint condition'),
('Signed Book Copy', 'Books', 299.99, 2, 'Author signed first edition'),
('Artisan Coffee Beans', 'Food & Beverage', 49.99, 8, 'Single origin, limited batch roast');

-- Create a simple audit log table for the demo
CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    action VARCHAR(50) NOT NULL,
    table_name VARCHAR(100),
    record_id INTEGER,
    details JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insert initial audit entry
INSERT INTO audit_log (action, table_name, details) VALUES
('SEED_DATA', 'products', '{"message": "Database seeded with demo data", "product_count": 33}');

-- Display summary
SELECT
    'Database seeded successfully!' as status,
    COUNT(*) as total_products,
    COUNT(DISTINCT category) as categories,
    SUM(quantity) as total_inventory,
    ROUND(SUM(price * quantity)::numeric, 2) as total_value
FROM products;
