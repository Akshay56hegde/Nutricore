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
    payment_mode = db.Column(db.String(50))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
