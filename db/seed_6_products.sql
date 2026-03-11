-- NutriCore: fresh product seed template (replace values before running)
-- Run this in MySQL Workbench on database: nutricore_db

-- Optional: clear all existing products
DELETE FROM products;

-- Insert 6 new products
INSERT INTO products
(name, protein_per_serving, price, brand, protein_type, rating, image_url)
VALUES
('Product 1 Name', 24, 1999, 'Brand 1', 'Whey', 4.5, '/images/products/product-1.jpg'),
('Product 2 Name', 25, 2199, 'Brand 2', 'Isolate', 4.6, '/images/products/product-2.jpg'),
('Product 3 Name', 22, 1899, 'Brand 3', 'Plant', 4.3, '/images/products/product-3.jpg'),
('Product 4 Name', 27, 2499, 'Brand 4', 'Mass Gainer', 4.4, '/images/products/product-4.jpg'),
('Product 5 Name', 23, 2099, 'Brand 5', 'Casein', 4.2, '/images/products/product-5.jpg'),
('Product 6 Name', 26, 2299, 'Brand 6', 'Whey', 4.7, '/images/products/product-6.jpg');

-- Verify inserted products
SELECT id, name, brand, protein_type, protein_per_serving, price, rating, image_url
FROM products
ORDER BY id DESC
LIMIT 20;
