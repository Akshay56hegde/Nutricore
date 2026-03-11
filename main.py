from flask import Flask, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import urllib.parse
import random
import smtplib
import os
import re
import json
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from sqlalchemy import inspect, text, or_, func
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from models import db, User, Product, IntakeLog, Order

app = Flask(__name__, static_url_path='', static_folder='static')
PLACEHOLDER_IMAGE = '/images/products/placeholder.svg'
LOCAL_IMAGE_PREFIX = '/images/products/'

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

EMAIL_HOST = os.getenv('EMAIL_HOST')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', 587))
EMAIL_USER = os.getenv('EMAIL_USER')
EMAIL_PASS = os.getenv('EMAIL_PASS')
EMAIL_SENDER = os.getenv('EMAIL_SENDER')

raw_password = "journeyBEGINS@1"
safe_password = urllib.parse.quote_plus(raw_password)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'nutricore-dev-secret')
app.config['SQLALCHEMY_DATABASE_URI'] = f'mysql+pymysql://root:{safe_password}@localhost/nutricore_db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])


def normalize_image_url(image_url):
    raw = (image_url or '').strip()
    if not raw:
        return PLACEHOLDER_IMAGE

    normalized = raw.replace('\\', '/')
    lowered = normalized.lower()

    if lowered.startswith(('http://', 'https://', 'data:')):
        return normalized

    if normalized.startswith('/'):
        return normalized

    if lowered.startswith('images/'):
        return f'/{normalized}'

    filename = normalized.split('/')[-1]
    return f'{LOCAL_IMAGE_PREFIX}{filename}'


def build_auth_token(user):
    return serializer.dumps({
        "user_id": user.id,
        "email": user.email,
        "is_admin": bool(user.is_admin)
    })


def get_authenticated_user(require_admin=False):
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return None, (jsonify({"message": "Authorization required"}), 401)

    token = auth_header.split(' ', 1)[1].strip()
    if not token:
        return None, (jsonify({"message": "Authorization required"}), 401)

    try:
        payload = serializer.loads(token, max_age=60 * 60 * 24)
    except SignatureExpired:
        return None, (jsonify({"message": "Session expired. Please login again."}), 401)
    except BadSignature:
        return None, (jsonify({"message": "Invalid session token"}), 401)

    user = User.query.get(payload.get('user_id'))
    if not user:
        return None, (jsonify({"message": "User not found"}), 401)

    if require_admin and not user.is_admin:
        return None, (jsonify({"message": "Admin access required"}), 403)

    return user, None


def create_order_number():
    stamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    suffix = f"{random.randint(100, 999)}"
    return f"NC{stamp}{suffix}"


def serialize_order(order, user=None):
    linked_user = user or User.query.get(order.user_id)
    items = []
    if order.items_summary:
        try:
            items = json.loads(order.items_summary)
        except json.JSONDecodeError:
            items = []

    return {
        "id": order.id,
        "order_number": order.order_number,
        "user_id": order.user_id,
        "user_name": linked_user.name if linked_user else 'Unknown',
        "user_email": linked_user.email if linked_user else '',
        "user_mobile": linked_user.mobile if linked_user else '',
        "total_price": order.total_price or 0,
        "item_count": order.item_count or 0,
        "payment_mode": order.payment_mode or 'Unknown',
        "payment_status": order.payment_status or 'Pending',
        "shipping_address": order.shipping_address or '',
        "items": items,
        "admin_notified": bool(order.admin_notified),
        "timestamp": order.timestamp.isoformat() if order.timestamp else None
    }


@app.route('/')
def index():
    return app.send_static_file('landingpage.html')


@app.route('/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    email = (data.get('email') or '').strip().lower()
    user = User.query.filter_by(email=email).first()

    if user and check_password_hash(user.password_hash, data.get('password', '')):
        weight = user.weight or 0
        goal = user.goal_multiplier or 1.2
        target = round(weight * goal, 1)
        return jsonify({
            "user": {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "target": target,
                "is_admin": bool(user.is_admin)
            },
            "token": build_auth_token(user)
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
    sort = (request.args.get('sort') or 'low-high').strip().lower()
    brand = (request.args.get('brand') or '').strip()
    protein_type = (request.args.get('protein_type') or '').strip()
    min_rating = request.args.get('min_rating', type=float)
    min_price = request.args.get('min_price', type=float)
    max_price = request.args.get('max_price', type=float)
    search_q = (request.args.get('q') or '').strip()

    query = Product.query

    if brand:
        query = query.filter(Product.brand == brand)
    if protein_type:
        query = query.filter(Product.protein_type == protein_type)
    if min_rating is not None:
        query = query.filter(Product.rating >= min_rating)
    if min_price is not None:
        query = query.filter(Product.price >= min_price)
    if max_price is not None:
        query = query.filter(Product.price <= max_price)
    if search_q:
        search_terms = [term for term in re.split(r"\s+", search_q) if term]
        for term in search_terms:
            like_term = f"%{term}%"
            query = query.filter(or_(
                Product.name.ilike(like_term),
                Product.brand.ilike(like_term),
                Product.protein_type.ilike(like_term)
            ))

    if sort == 'high-low':
        query = query.order_by(Product.price.desc())
    else:
        query = query.order_by(Product.price.asc())

    products = query.all()
    return jsonify([
        {
            "id": p.id,
            "name": p.name,
            "protein": p.protein_per_serving,
            "price": p.price,
            "brand": p.brand or 'NutriCore',
            "protein_type": p.protein_type or 'Whey',
            "rating": p.rating or 4.0,
            "image_url": normalize_image_url(p.image_url)
        }
        for p in products
    ])


@app.route('/checkout', methods=['POST'])
def checkout():
    data = request.get_json() or {}
    user_id = data.get('user_id')
    product_ids = data.get('product_ids') or []
    shipping_address = (data.get('shipping_address') or '').strip()
    payment_mode = (data.get('payment_mode') or 'UPI').strip()
    payment_status = (data.get('payment_status') or 'Paid').strip()

    if not user_id:
        return jsonify({"message": "User ID required"}), 400

    if not shipping_address:
        return jsonify({"message": "Shipping address is required"}), 400

    user = User.query.get(user_id)
    if not user:
        return jsonify({"message": "User not found"}), 404

    total_protein = 0
    total_price = 0
    item_count = 0
    line_items = []

    for p_id in product_ids:
        product = Product.query.get(p_id)
        if not product:
            continue

        total_protein += product.protein_per_serving or 0
        total_price += product.price or 0
        item_count += 1
        line_items.append({
            "product_id": product.id,
            "name": product.name,
            "price": float(product.price or 0),
            "protein": float(product.protein_per_serving or 0)
        })
        db.session.add(IntakeLog(
            user_id=user_id,
            product_name=product.name,
            protein_consumed=product.protein_per_serving or 0
        ))

    if not item_count:
        return jsonify({"message": "No valid products selected"}), 400

    order = Order(
        order_number=create_order_number(),
        user_id=user_id,
        total_price=total_price,
        item_count=item_count,
        payment_mode=payment_mode,
        payment_status=payment_status,
        shipping_address=shipping_address,
        items_summary=json.dumps(line_items),
        admin_notified=False
    )
    db.session.add(order)
    db.session.commit()

    return jsonify({
        "status": "Payment Successful",
        "invoice": {
            "order_number": order.order_number,
            "total_price": total_price,
            "total_protein_gained": total_protein,
            "message": "Invoice sent to registered email."
        }
    }), 200


@app.route('/admin/stats')
def admin_stats():
    admin_user, error = get_authenticated_user(require_admin=True)
    if error:
        return error

    return jsonify({
        "total_users": User.query.filter_by(is_admin=False).count(),
        "total_products": Product.query.count(),
        "total_orders": Order.query.count(),
        "pending_notifications": Order.query.filter_by(admin_notified=False).count(),
        "total_revenue": round(db.session.query(func.coalesce(func.sum(Order.total_price), 0)).scalar() or 0, 2)
    })


@app.route('/admin/users')
def get_admin_users():
    admin_user, error = get_authenticated_user(require_admin=True)
    if error:
        return error

    users = User.query.filter_by(is_admin=False).order_by(User.name.asc()).all()
    payload = []
    for u in users:
        history = IntakeLog.query.filter_by(user_id=u.id).order_by(IntakeLog.id.desc()).all()
        orders = Order.query.filter_by(user_id=u.id).order_by(Order.timestamp.desc()).all()
        payload.append({
            "id": u.id,
            "name": u.name,
            "email": u.email,
            "mobile": u.mobile,
            "weight": u.weight or 0,
            "target": round((u.weight or 0) * (u.goal_multiplier or 1.2), 1),
            "history": [
                {
                    "product_name": log.product_name,
                    "protein_consumed": log.protein_consumed or 0
                }
                for log in history
            ],
            "orders": [serialize_order(order, u) for order in orders]
        })
    return jsonify(payload)


@app.route('/admin/orders')
def get_admin_orders():
    admin_user, error = get_authenticated_user(require_admin=True)
    if error:
        return error

    orders = Order.query.order_by(Order.timestamp.desc()).all()
    users = {
        user.id: user
        for user in User.query.filter(User.id.in_([order.user_id for order in orders])).all()
    } if orders else {}
    return jsonify([serialize_order(order, users.get(order.user_id)) for order in orders])


@app.route('/admin/orders/<int:order_id>/mark-read', methods=['POST'])
def mark_admin_order_read(order_id):
    admin_user, error = get_authenticated_user(require_admin=True)
    if error:
        return error

    order = Order.query.get(order_id)
    if not order:
        return jsonify({"message": "Order not found"}), 404

    order.admin_notified = True
    db.session.commit()
    return jsonify({"message": "Notification marked as read"}), 200


@app.route('/admin/add-product', methods=['POST'])
def add_product():
    admin_user, error = get_authenticated_user(require_admin=True)
    if error:
        return error

    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({"message": "Product name is required"}), 400

    new_product = Product(
        name=name,
        protein_per_serving=float(data.get('protein') or 0),
        price=float(data.get('price') or 0),
        brand=data.get('brand') or 'NutriCore',
        protein_type=data.get('protein_type') or 'Whey',
        rating=None,
        image_url=normalize_image_url(data.get('image_url'))
    )
    db.session.add(new_product)
    db.session.commit()

    return jsonify({"message": "Product Added!"}), 201


@app.route('/admin/delete-product/<int:product_id>', methods=['DELETE'])
def delete_product(product_id):
    admin_user, error = get_authenticated_user(require_admin=True)
    if error:
        return error

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
        product_indexes = {idx['name'] for idx in inspector.get_indexes('products')}
        if 'brand' not in product_cols:
            db.session.execute(text("ALTER TABLE products ADD COLUMN brand VARCHAR(50) NULL"))
        if 'protein_type' not in product_cols:
            db.session.execute(text("ALTER TABLE products ADD COLUMN protein_type VARCHAR(50) NULL"))
        if 'rating' not in product_cols:
            db.session.execute(text("ALTER TABLE products ADD COLUMN rating FLOAT NULL"))
        if 'image_url' not in product_cols:
            db.session.execute(text("ALTER TABLE products ADD COLUMN image_url VARCHAR(500) NULL"))
        if 'idx_products_name' not in product_indexes:
            db.session.execute(text("CREATE INDEX idx_products_name ON products (name)"))
        if 'idx_products_brand' not in product_indexes:
            db.session.execute(text("CREATE INDEX idx_products_brand ON products (brand)"))
        if 'idx_products_type' not in product_indexes:
            db.session.execute(text("CREATE INDEX idx_products_type ON products (protein_type)"))

    if 'orders' in inspector.get_table_names():
        order_cols = {col['name'] for col in inspector.get_columns('orders')}
        if 'item_count' not in order_cols:
            db.session.execute(text("ALTER TABLE orders ADD COLUMN item_count INT DEFAULT 0"))
        if 'payment_status' not in order_cols:
            db.session.execute(text("ALTER TABLE orders ADD COLUMN payment_status VARCHAR(50) DEFAULT 'Pending'"))
        if 'shipping_address' not in order_cols:
            db.session.execute(text("ALTER TABLE orders ADD COLUMN shipping_address TEXT NULL"))
        if 'items_summary' not in order_cols:
            db.session.execute(text("ALTER TABLE orders ADD COLUMN items_summary TEXT NULL"))
        if 'admin_notified' not in order_cols:
            db.session.execute(text("ALTER TABLE orders ADD COLUMN admin_notified BOOLEAN DEFAULT FALSE"))

    db.session.commit()


def ensure_admin_account():
    admin_email = 'nutricoreadmin@gmail.com'
    admin_password = 'Admin@123'

    admin = User.query.filter_by(email=admin_email).first()
    if admin:
        admin.is_admin = True
        if not admin.mobile:
            admin.mobile = None
        admin.password_hash = generate_password_hash(admin_password, method='pbkdf2:sha256')
        db.session.commit()
        return

    legacy_admin = User.query.filter(User.email.in_(['admin@nutricore.com', 'adminnutricore@gmail.com'])).first()
    if legacy_admin:
        legacy_admin.email = admin_email
        legacy_admin.name = legacy_admin.name or 'Admin'
        legacy_admin.is_admin = True
        legacy_admin.password_hash = generate_password_hash(admin_password, method='pbkdf2:sha256')
        db.session.commit()
        return

    db.session.add(User(
        name='Admin',
        email=admin_email,
        password_hash=generate_password_hash(admin_password, method='pbkdf2:sha256'),
        is_admin=True,
        weight=70,
        goal_multiplier=1.2
    ))
    db.session.commit()


def seed_products_if_empty():
    if Product.query.count() > 0:
        return

    seed_products = [
        {
            "name": "Optimum Nutrition Gold Standard Whey",
            "protein_per_serving": 24,
            "price": 68,
            "brand": "Optimum Nutrition",
            "protein_type": "Whey",
            "rating": 4.8,
            "image_url": "https://images.unsplash.com/photo-1599058917212-d750089bc07e"
        },
        {
            "name": "Dymatize ISO100",
            "protein_per_serving": 25,
            "price": 72,
            "brand": "Dymatize",
            "protein_type": "Isolate",
            "rating": 4.7,
            "image_url": "https://images.unsplash.com/photo-1622484212850-eb596d769edc"
        },
        {
            "name": "MyProtein Impact Whey",
            "protein_per_serving": 21,
            "price": 52,
            "brand": "MyProtein",
            "protein_type": "Whey",
            "rating": 4.5,
            "image_url": "https://images.unsplash.com/photo-1579722821273-0f6c7d44362f"
        },
        {
            "name": "BSN Syntha-6",
            "protein_per_serving": 22,
            "price": 55,
            "brand": "BSN",
            "protein_type": "Whey",
            "rating": 4.6,
            "image_url": "https://images.unsplash.com/photo-1622483767028-3f66f32aef97"
        },
        {
            "name": "Whey Isolate Plus",
            "protein_per_serving": 27,
            "price": 79,
            "brand": "NutriCore",
            "protein_type": "Isolate",
            "rating": 4.7,
            "image_url": "https://images.unsplash.com/photo-1549570652-97324981a6fd"
        },
        {
            "name": "Plant Protein Blend",
            "protein_per_serving": 20,
            "price": 47,
            "brand": "NutriCore",
            "protein_type": "Plant",
            "rating": 4.4,
            "image_url": "https://images.unsplash.com/photo-1521804906057-1df8fdb718b7"
        },
        {
            "name": "Mass Gainer Pro",
            "protein_per_serving": 30,
            "price": 74,
            "brand": "NutriCore",
            "protein_type": "Mass Gainer",
            "rating": 4.6,
            "image_url": "https://images.unsplash.com/photo-1605296867304-46d5465a13f1"
        },
        {
            "name": "Casein Night Recovery",
            "protein_per_serving": 24,
            "price": 63,
            "brand": "NutriCore",
            "protein_type": "Casein",
            "rating": 4.5,
            "image_url": "https://images.unsplash.com/photo-1574680178050-55c6a6a96e0a"
        }
    ]

    for p in seed_products:
        db.session.add(Product(
            name=p["name"],
            protein_per_serving=p["protein_per_serving"],
            price=p["price"],
            brand=p["brand"],
            protein_type=p["protein_type"],
            rating=p["rating"],
            image_url=p["image_url"]
        ))
    db.session.commit()


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        ensure_schema_compatibility()
        seed_products_if_empty()
        ensure_admin_account()

    app.run(debug=True)
