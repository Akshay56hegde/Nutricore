NutriCore Product Images - Setup Guide

1) Save all new product images in this folder:
   static/images/products/

2) Use simple lowercase file names, for example:
   product-1.jpg
   product-2.jpg
   product-3.jpg
   product-4.jpg
   product-5.jpg
   product-6.jpg

3) In DB seed SQL, image paths must use this format:
   /images/products/<file-name>
   Example: /images/products/product-1.jpg

4) Do not use Windows absolute paths in SQL
   (wrong): C:\Users\...\product-1.jpg
   (correct): /images/products/product-1.jpg

5) After updating SQL, run:
   db/seed_6_products.sql

6) Restart Flask app and refresh homepage.

If an image path is wrong or file is missing, placeholder.svg is shown.
