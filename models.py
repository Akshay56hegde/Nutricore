from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50))
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    weight = db.Column(db.Float)
    goal_multiplier = db.Column(db.Float)

class Product(db.Model):
    __tablename__ = "products"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    protein_per_serving = db.Column(db.Float)
    price = db.Column(db.Float)

class IntakeLog(db.Model):
    __tablename__ = "intake_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    product_name = db.Column(db.String(100))
    protein_consumed = db.Column(db.Float)