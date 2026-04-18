from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50))
    email = db.Column(db.String(120), unique=True, nullable=False)
    mobile = db.Column(db.String(10), unique=True, nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    weight = db.Column(db.Float)
    goal_multiplier = db.Column(db.Float)
    reset_token = db.Column(db.String(100), nullable=True)
    reset_token_expiry = db.Column(db.DateTime, nullable=True)

class Product(db.Model):
    __tablename__ = "products"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    protein_per_serving = db.Column(db.Float)
    net_quantity = db.Column(db.String(50))
    price = db.Column(db.Float)
    brand = db.Column(db.String(50))
    protein_type = db.Column(db.String(50))
    rating = db.Column(db.Float)
    image_url = db.Column(db.String(500))

class ProductRating(db.Model):
    __tablename__ = "product_ratings"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    review = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class IntakeLog(db.Model):
    __tablename__ = "intake_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    product_name = db.Column(db.String(100))
    protein_consumed = db.Column(db.Float)

class Order(db.Model):
    __tablename__ = "orders"
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(20), unique=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    total_price = db.Column(db.Float)
    item_count = db.Column(db.Integer, default=0)
    payment_mode = db.Column(db.String(50))
    payment_status = db.Column(db.String(50), default="Pending")
    shipping_address = db.Column(db.Text)
    items_summary = db.Column(db.Text)
    admin_notified = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class Offer(db.Model):
    __tablename__ = "offers"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), unique=True, nullable=False)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    badge = db.Column(db.String(40))
    cta_note = db.Column(db.String(160))
    discount_type = db.Column(db.String(20))
    discount_value = db.Column(db.Float)
    min_order_amount = db.Column(db.Float)
    max_discount = db.Column(db.Float)
    condition_text = db.Column(db.String(200))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
