from flask import Flask, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import urllib.parse
import random
import smtplib
import os
import re
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from sqlalchemy import inspect, text
from models import db, User, Product, IntakeLog, Order

app = Flask(__name__, static_url_path='', static_folder='static')

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

EMAIL_HOST = os.getenv('EMAIL_HOST')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', 587))
EMAIL_USER = os.getenv('EMAIL_USER')
EMAIL_PASS = os.getenv('EMAIL_PASS')
EMAIL_SENDER = os.getenv('EMAIL_SENDER')

raw_password = "journeyBEGINS@1"
safe_password = urllib.parse.quote_plus(raw_password)
app.config['SQLALCHEMY_DATABASE_URI'] = f'mysql+pymysql://root:{safe_password}@localhost/nutricore_db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)


@app.route('/')
def index():
    return app.send_static_file('index.html')


@app.route('/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    user = User.query.filter_by(email=(data.get('email') or '').strip()).first()

    if user and check_password_hash(user.password_hash, data.get('password', '')):
        weight = user.weight or 0
        goal = user.goal_multiplier or 1.2
        target = round(weight * goal, 1)
        return jsonify({
            "user": {
                "id": user.id,
                "name": user.name,
                "target": target,
                "is_admin": bool(user.is_admin)
            }
        }), 200

    return jsonify({"message": "Invalid credentials"}), 401


@app.route('/register', methods=['POST'])
def register():
    data = request.get_json() or {}

    name = (data.get('name') or data.get('username') or '').strip()
    email = (data.get('email') or '').strip().lower()
    mobile = (data.get('mobile') or '').strip()
    password = data.get('password') or ''

    if not name or not email or not mobile or not password:
        return jsonify({"message": "Name, email, mobile and password are required"}), 400

    if not email.endswith('@gmail.com'):
        return jsonify({"message": "Invalid email"}), 400

    if not re.fullmatch(r"^[0-9]{10}$", mobile):
        return jsonify({"message": "Invalid mobile number"}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"message": "Email exists"}), 400
    if User.query.filter_by(mobile=mobile).first():
        return jsonify({"message": "Mobile number exists"}), 400

    if (len(password) < 8 or not re.search(r"[a-z]", password)
            or not re.search(r"[A-Z]", password)
            or not re.search(r"[0-9]", password)
            or not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password)):
        return jsonify({"message": "Password is weak. Ensure it has 8+ chars, uppercase, lowercase, number, and special char."}), 400

    new_user = User(
        name=name,
        email=email,
        mobile=mobile,
        password_hash=generate_password_hash(password, method='pbkdf2:sha256'),
        is_admin=False,
        weight=float(data.get('weight') or 0),
        goal_multiplier=float(data.get('goal_multiplier') or 1.2)
    )
    db.session.add(new_user)
    db.session.commit()

    return jsonify({"message": "Success"}), 201


@app.route('/forgot-password', methods=['POST'])
def forgot_password():
    data = request.get_json() or {}
    email = (data.get('email') or '').strip().lower()

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"message": "Email not found"}), 404

    otp = str(random.randint(100000, 999999))
    user.reset_token = otp
    user.reset_token_expiry = datetime.utcnow() + timedelta(hours=1)
    db.session.commit()

    # Try sending OTP by email; if config is missing, still return success for local/dev use.
    if EMAIL_HOST and EMAIL_USER and EMAIL_PASS and EMAIL_SENDER:
        try:
            msg = MIMEMultipart()
            msg['From'] = EMAIL_SENDER
            msg['To'] = user.email
            msg['Subject'] = 'NutriCore Password Reset OTP'
            msg.attach(MIMEText(f"Your NutriCore OTP is: {otp}\nValid for 1 hour.", 'plain'))

            server = smtplib.SMTP(EMAIL_HOST, EMAIL_PORT)
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_SENDER, user.email, msg.as_string())
            server.quit()
            return jsonify({"message": "OTP sent to your email"}), 200
        except Exception:
            # Keep flow usable if SMTP setup is temporarily broken.
            return jsonify({"message": "OTP generated. Email send failed; check SMTP config.", "otp": otp}), 200

    return jsonify({"message": "OTP generated. Configure SMTP to deliver by email.", "otp": otp}), 200


@app.route('/reset-password', methods=['POST'])
def reset_password():
    data = request.get_json() or {}

    user = User.query.filter_by(email=(data.get('email') or '').strip().lower()).first()
    otp = (data.get('otp') or '').strip()
    new_password = data.get('new_password') or ''

    if not user or user.reset_token != otp:
        return jsonify({"message": "Invalid OTP"}), 400

    if not user.reset_token_expiry or user.reset_token_expiry < datetime.utcnow():
        return jsonify({"message": "OTP expired"}), 400

    if len(new_password) < 8:
        return jsonify({"message": "Password must be at least 8 characters"}), 400

    user.password_hash = generate_password_hash(new_password, method='pbkdf2:sha256')
    user.reset_token = None
    user.reset_token_expiry = None
    db.session.commit()

    return jsonify({"message": "Password updated successfully"}), 200


@app.route('/user/update-details', methods=['POST'])
def update_user_details():
    data = request.get_json() or {}
    user_id = data.get('user_id')

    if not user_id:
        return jsonify({"message": "User ID required"}), 400

    user = User.query.get(user_id)
    if not user:
        return jsonify({"message": "User not found"}), 404

    try:
        user.weight = float(data.get('weight') or 0)
        user.goal_multiplier = float(data.get('goal') or 1.2)
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({"message": "Invalid input for weight/goal"}), 400

    target = round((user.weight or 0) * (user.goal_multiplier or 1.2), 1)
    return jsonify({"message": "Details updated", "target": target}), 200


@app.route('/products')
def get_products():
    products = Product.query.all()
    return jsonify([
        {
            "id": p.id,
            "name": p.name,
            "protein": p.protein_per_serving,
            "price": p.price,
            "brand": p.brand or 'NutriCore'
        }
        for p in products
    ])


@app.route('/checkout', methods=['POST'])
def checkout():
    data = request.get_json() or {}
    user_id = data.get('user_id')
    product_ids = data.get('product_ids') or []

    total_protein = 0
    total_price = 0

    for p_id in product_ids:
        product = Product.query.get(p_id)
        if not product:
            continue

        total_protein += product.protein_per_serving or 0
        total_price += product.price or 0
        db.session.add(IntakeLog(
            user_id=user_id,
            product_name=product.name,
            protein_consumed=product.protein_per_serving or 0
        ))

    db.session.commit()

    return jsonify({
        "status": "Payment Successful",
        "invoice": {
            "total_price": total_price,
            "total_protein_gained": total_protein,
            "message": "Invoice sent to registered email."
        }
    }), 200


@app.route('/admin/stats')
def admin_stats():
    return jsonify({
        "total_users": User.query.filter_by(is_admin=False).count(),
        "total_products": Product.query.count(),
        "total_orders": Order.query.count()
    })


@app.route('/admin/users')
def get_admin_users():
    users = User.query.filter_by(is_admin=False).all()
    return jsonify([
        {"name": u.name, "email": u.email, "mobile": u.mobile, "weight": u.weight or 0}
        for u in users
    ])


@app.route('/admin/add-product', methods=['POST'])
def add_product():
    data = request.get_json() or {}

    new_product = Product(
        name=data.get('name'),
        protein_per_serving=float(data.get('protein') or 0),
        price=float(data.get('price') or 0),
        brand=data.get('brand') or 'NutriCore'
    )
    db.session.add(new_product)
    db.session.commit()

    return jsonify({"message": "Product Added!"}), 201


@app.route('/admin/delete-product/<int:product_id>', methods=['DELETE'])
def delete_product(product_id):
    product = Product.query.get(product_id)
    if not product:
        return jsonify({"message": "Product not found"}), 404

    db.session.delete(product)
    db.session.commit()
    return jsonify({"message": "Deleted"}), 200


def ensure_schema_compatibility():
    inspector = inspect(db.engine)

    if 'users' in inspector.get_table_names():
        user_cols = {col['name'] for col in inspector.get_columns('users')}
        if 'is_admin' not in user_cols:
            db.session.execute(text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT FALSE"))
        if 'reset_token' not in user_cols:
            db.session.execute(text("ALTER TABLE users ADD COLUMN reset_token VARCHAR(100) NULL"))
        if 'reset_token_expiry' not in user_cols:
            db.session.execute(text("ALTER TABLE users ADD COLUMN reset_token_expiry DATETIME NULL"))
        if 'mobile' not in user_cols:
            db.session.execute(text("ALTER TABLE users ADD COLUMN mobile VARCHAR(10) NULL"))

    if 'products' in inspector.get_table_names():
        product_cols = {col['name'] for col in inspector.get_columns('products')}
        if 'brand' not in product_cols:
            db.session.execute(text("ALTER TABLE products ADD COLUMN brand VARCHAR(50) NULL"))

    db.session.commit()


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        ensure_schema_compatibility()

        admin = User.query.filter_by(email='admin@nutricore.com').first()
        if not admin:
            admin = User(
                name='Admin',
                email='admin@nutricore.com',
                password_hash=generate_password_hash('Admin@123', method='pbkdf2:sha256'),
                is_admin=True,
                weight=70,
                goal_multiplier=1.2
            )
            db.session.add(admin)
            db.session.commit()

    app.run(debug=True)
