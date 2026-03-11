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
    price = db.Column(db.Float)
    brand = db.Column(db.String(50))
    protein_type = db.Column(db.String(50))
    rating = db.Column(db.Float)
    image_url = db.Column(db.String(500))

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
