from flask import Flask, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
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
from models import db, User, Product, ProductRating, IntakeLog, Order, Offer

app = Flask(__name__, static_url_path='', static_folder='static')
PLACEHOLDER_IMAGE = '/images/products/placeholder.svg'
LOCAL_IMAGE_PREFIX = '/images/products/'
PRODUCT_IMAGE_DIR = os.path.join(app.static_folder, 'images', 'products', 'uploads')
ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}

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
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 86400

db.init_app(app)
serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])

PROTEIN_TYPE_CONCENTRATE = "Whey Protein Concentrate"
PROTEIN_TYPE_ISOLATE = "Whey Protein Isolate"
PROTEIN_TYPE_HYDROLYSATE = "Whey Protein Hydrolysate"
PROTEIN_TYPE_CASEIN = "Casein Protein"
PROTEIN_TYPE_PLANT = "Plant-Based Protein"


@app.after_request
def disable_html_cache(response):
    if request.path.endswith('.html') or response.mimetype == 'text/html':
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    elif request.path.startswith('/images/') or request.path.startswith('/static/'):
        response.headers['Cache-Control'] = 'public, max-age=86400'
    return response


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


def ensure_product_image_dir():
    os.makedirs(PRODUCT_IMAGE_DIR, exist_ok=True)


def is_allowed_image(filename):
    _, ext = os.path.splitext(filename or '')
    return ext.lower() in ALLOWED_IMAGE_EXTENSIONS


def get_nutricore_plan(weight, height, age, gender, activity, goal, is_sensitive, is_vegan):
    height_m = height / 100
    bmi = weight / (height_m * height_m) if height_m > 0 else 0

    if gender == "Male":
        bmr = (10 * weight) + (6.25 * height) - (5 * age) + 5
    else:
        bmr = (10 * weight) + (6.25 * height) - (5 * age) - 161

    multipliers = {
        "Little to No Exercise": 1.2,
        "Lightly Active": 1.375,
        "Moderately Active": 1.55,
        "Very Active": 1.725
    }
    tdee = bmr * multipliers[activity]

    if goal == "Weight Gain":
        target_protein = weight * 1.5
    elif goal == "Muscle Gain":
        target_protein = weight * 2.0
    elif goal == "Weight Loss":
        target_protein = weight * 2.2
    else:
        target_protein = weight * 1.2

    if is_vegan:
        protein_type = PROTEIN_TYPE_PLANT
        why = (
            "Plant-Based Protein fits best because it keeps your plan fully dairy-free while still supporting your daily protein target. "
            "It is a strong choice for vegan users, lactose intolerance, or anyone who wants a gentler non-dairy option."
        )
    elif activity == "Very Active" and goal in {"Muscle Gain", "Weight Loss"} and not is_sensitive:
        protein_type = PROTEIN_TYPE_HYDROLYSATE
        why = (
            "Whey Protein Hydrolysate fits best when training demand is high and fast recovery matters most. "
            "It is a premium option for athlete-level performance and quick post-workout protein delivery."
        )
    elif is_sensitive or goal == "Weight Loss":
        protein_type = PROTEIN_TYPE_ISOLATE
        why = (
            "Whey Protein Isolate fits best when you want high protein with lower carbs and fats for lean muscle or fat-loss goals. "
            "It is also easier to tolerate for many users with lactose sensitivity."
        )
    elif goal == "Maintenance" or (activity in {"Little to No Exercise", "Lightly Active"} and age >= 30):
        protein_type = PROTEIN_TYPE_CASEIN
        why = (
            "Casein Protein fits best when you need slower digestion across long gaps between meals or before sleep. "
            "It supports muscle preservation and can help with hunger control over a longer period."
        )
    else:
        protein_type = PROTEIN_TYPE_CONCENTRATE
        why = (
            "Whey Protein Concentrate fits best for beginners, budget-focused plans, and general muscle gain with a calorie surplus. "
            "It is a practical everyday option when lactose sensitivity is not a major concern."
        )

    return {
        "calories": round(tdee),
        "protein_grams": round(target_protein),
        "recommended_type": protein_type,
        "reason": why,
        "criteria": {
            "bmi": round(bmi, 1),
            "goal": goal,
            "activity": activity,
            "is_sensitive": bool(is_sensitive),
            "is_vegan": bool(is_vegan)
        }
    }


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


def get_optional_authenticated_user():
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return None

    token = auth_header.split(' ', 1)[1].strip()
    if not token:
        return None

    try:
        payload = serializer.loads(token, max_age=60 * 60 * 24)
    except (SignatureExpired, BadSignature):
        return None

    return User.query.get(payload.get('user_id'))


def build_product_rating_subquery():
    return db.session.query(
        ProductRating.product_id.label('product_id'),
        func.avg(ProductRating.rating).label('avg_rating'),
        func.count(ProductRating.id).label('rating_count')
    ).group_by(ProductRating.product_id).subquery()


def serialize_product_review(product_rating):
    linked_user = User.query.get(product_rating.user_id)
    return {
        "id": product_rating.id,
        "user_name": linked_user.name if linked_user else 'Anonymous',
        "rating": int(product_rating.rating or 0),
        "review": (product_rating.review or '').strip(),
        "created_at": product_rating.created_at.isoformat() if product_rating.created_at else None,
        "updated_at": product_rating.updated_at.isoformat() if product_rating.updated_at else None
    }


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


def serialize_offer(offer):
    return {
        "id": offer.id,
        "code": offer.code,
        "title": offer.title,
        "description": offer.description or '',
        "badge": offer.badge or 'Active',
        "cta_note": offer.cta_note or '',
        "discount_type": offer.discount_type or '',
        "discount_value": offer.discount_value if offer.discount_value is not None else None,
        "min_order_amount": offer.min_order_amount if offer.min_order_amount is not None else None,
        "max_discount": offer.max_discount if offer.max_discount is not None else None,
        "condition_text": offer.condition_text or '',
        "is_active": bool(offer.is_active),
        "created_at": offer.created_at.isoformat() if offer.created_at else None
    }


def parse_optional_float(value, field_name):
    raw = str(value or '').strip()
    if not raw:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a valid number")


def build_offer_condition_text(discount_type, discount_value=None, min_order_amount=None, max_discount=None):
    normalized_type = (discount_type or '').strip().lower()
    parts = []

    if normalized_type == 'percentage' and discount_value is not None:
        parts.append(f"{discount_value:g}% off")
    elif normalized_type == 'fixed' and discount_value is not None:
        parts.append(f"Rs. {discount_value:g} off")
    elif normalized_type == 'free_shipping':
        parts.append("Free shipping")
    else:
        parts.append("Special offer")

    if min_order_amount is not None:
        parts.append(f"on orders above Rs. {min_order_amount:g}")

    if normalized_type == 'percentage' and max_discount is not None:
        parts.append(f"up to Rs. {max_discount:g}")

    return ' '.join(parts).strip()


@app.route('/')
def index():
    return app.send_static_file('landingpage.html')


@app.route('/calculator')
def calculator_page():
    return app.send_static_file('calculator.html')


@app.route('/homepage')
def homepage_page():
    return app.send_static_file('homepage.html')


@app.route('/store')
def store_page():
    return app.send_static_file('homepage.html')


@app.route('/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    email = (data.get('email') or '').strip().lower()
    user = User.query.filter_by(email=email).first()

    if user and check_password_hash(user.password_hash, data.get('password', '')):
        weight = user.weight or 0
        goal = user.goal_multiplier or 1.2
        target = round(weight * goal, 1)
        response = jsonify({
            "user": {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "mobile": user.mobile,
                "weight": user.weight or 0,
                "goal_multiplier": user.goal_multiplier or 1.2,
                "target": target,
                "is_admin": bool(user.is_admin)
            },
            "token": build_auth_token(user)
        })
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        response.headers['Clear-Site-Data'] = '"cache"'
        return response, 200

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


@app.route('/user/profile', methods=['GET'])
def get_user_profile():
    user, error = get_authenticated_user(require_admin=False)
    if error:
        return error

    return jsonify({
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "mobile": user.mobile,
        "is_admin": bool(user.is_admin),
        "weight": user.weight or 0,
        "goal_multiplier": user.goal_multiplier or 1.2
    }), 200


@app.route('/user/profile', methods=['POST'])
def update_user_profile():
    user, error = get_authenticated_user(require_admin=False)
    if error:
        return error

    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    mobile = (data.get('mobile') or '').strip()

    if not name or not email or not mobile:
        return jsonify({"message": "Name, email and mobile are required"}), 400

    if not email.endswith('@gmail.com'):
        return jsonify({"message": "Enter a valid Gmail address"}), 400

    if not re.fullmatch(r"^[0-9]{10}$", mobile):
        return jsonify({"message": "Enter a valid 10-digit mobile number"}), 400

    existing_email = User.query.filter(User.email == email, User.id != user.id).first()
    if existing_email:
        return jsonify({"message": "Email already exists"}), 400

    existing_mobile = User.query.filter(User.mobile == mobile, User.id != user.id).first()
    if existing_mobile:
        return jsonify({"message": "Mobile number already exists"}), 400

    user.name = name
    user.email = email
    user.mobile = mobile
    db.session.commit()

    return jsonify({
        "message": "Profile updated successfully",
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "mobile": user.mobile,
            "is_admin": bool(user.is_admin),
            "target": round((user.weight or 0) * (user.goal_multiplier or 1.2), 1)
        }
    }), 200


@app.route('/api/calculator', methods=['POST'])
def calculate_nutricore_plan():
    data = request.get_json() or {}

    try:
        weight = float(data.get('weight') or 0)
        height = float(data.get('height') or 0)
        age = int(data.get('age') or 0)
    except (TypeError, ValueError):
        return jsonify({"message": "Weight, height and age must be valid numbers"}), 400

    gender = (data.get('gender') or '').strip()
    activity = (data.get('activity') or '').strip()
    goal = (data.get('goal') or '').strip()
    is_sensitive = bool(data.get('is_sensitive'))
    is_vegan = bool(data.get('is_vegan'))

    valid_genders = {"Male", "Female"}
    valid_activities = {
        "Little to No Exercise",
        "Lightly Active",
        "Moderately Active",
        "Very Active"
    }
    valid_goals = {"Weight Gain", "Muscle Gain", "Weight Loss", "Maintenance"}

    if weight <= 0 or height <= 0 or age <= 0:
        return jsonify({"message": "Weight, height and age must be greater than zero"}), 400
    if gender not in valid_genders:
        return jsonify({"message": "Please select a valid gender"}), 400
    if activity not in valid_activities:
        return jsonify({"message": "Please select a valid activity level"}), 400
    if goal not in valid_goals:
        return jsonify({"message": "Please select a valid fitness goal"}), 400

    result = get_nutricore_plan(
        weight=weight,
        height=height,
        age=age,
        gender=gender,
        activity=activity,
        goal=goal,
        is_sensitive=is_sensitive,
        is_vegan=is_vegan
    )

    return jsonify({
        "inputs": {
            "weight": weight,
            "height": height,
            "age": age,
            "gender": gender,
            "activity": activity,
            "goal": goal,
            "is_sensitive": is_sensitive,
            "is_vegan": is_vegan
        },
        "plan": result
    }), 200


@app.route('/products')
def get_products():
    sort = (request.args.get('sort') or 'low-high').strip().lower()
    brand = (request.args.get('brand') or '').strip()
    protein_type = (request.args.get('protein_type') or '').strip()
    min_rating = request.args.get('min_rating', type=float)
    min_price = request.args.get('min_price', type=float)
    max_price = request.args.get('max_price', type=float)
    search_q = (request.args.get('q') or '').strip()

    current_user = get_optional_authenticated_user()
    rating_subquery = build_product_rating_subquery()
    query = db.session.query(
        Product,
        rating_subquery.c.avg_rating,
        rating_subquery.c.rating_count
    ).outerjoin(rating_subquery, Product.id == rating_subquery.c.product_id)

    if brand:
        query = query.filter(Product.brand == brand)
    if protein_type:
        query = query.filter(Product.protein_type == protein_type)
    if min_rating is not None:
        query = query.filter(func.coalesce(rating_subquery.c.avg_rating, 0) >= min_rating)
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
    user_ratings = {}
    if current_user and products:
        product_ids = [product.id for product, _, _ in products]
        user_ratings = {
            row.product_id: {
                "rating": row.rating,
                "review": (row.review or '').strip()
            }
            for row in ProductRating.query.filter(
                ProductRating.user_id == current_user.id,
                ProductRating.product_id.in_(product_ids)
            ).all()
        }

    return jsonify([
        {
            "id": product.id,
            "name": product.name,
            "protein": product.protein_per_serving,
            "quantity": product.net_quantity or '',
            "price": product.price,
            "brand": product.brand or 'NutriCore',
            "protein_type": product.protein_type or PROTEIN_TYPE_CONCENTRATE,
            "rating": round(float(avg_rating), 1) if avg_rating is not None else None,
            "rating_count": int(rating_count or 0),
            "user_rating": (user_ratings.get(product.id) or {}).get("rating"),
            "user_review": (user_ratings.get(product.id) or {}).get("review", ''),
            "image_url": normalize_image_url(product.image_url)
        }
        for product, avg_rating, rating_count in products
    ])


@app.route('/products/<int:product_id>/reviews', methods=['GET'])
def get_product_reviews(product_id):
    product = Product.query.get(product_id)
    if not product:
        return jsonify({"message": "Product not found"}), 404

    summary = db.session.query(
        func.avg(ProductRating.rating).label('avg_rating'),
        func.count(ProductRating.id).label('rating_count')
    ).filter(ProductRating.product_id == product_id).first()

    reviews = ProductRating.query.filter_by(product_id=product_id).order_by(
        ProductRating.updated_at.desc(),
        ProductRating.created_at.desc()
    ).all()

    current_user = get_optional_authenticated_user()
    current_user_review = None
    if current_user:
        own_review = next((row for row in reviews if row.user_id == current_user.id), None)
        if own_review:
            current_user_review = {
                "rating": int(own_review.rating or 0),
                "review": (own_review.review or '').strip()
            }

    return jsonify({
        "product": {
            "id": product.id,
            "name": product.name
        },
        "rating": round(float(summary.avg_rating), 1) if summary.avg_rating is not None else None,
        "rating_count": int(summary.rating_count or 0),
        "current_user_review": current_user_review,
        "reviews": [serialize_product_review(review) for review in reviews]
    }), 200


@app.route('/products/<int:product_id>/rating', methods=['POST'])
def rate_product(product_id):
    user, error = get_authenticated_user(require_admin=False)
    if error:
        return error

    product = Product.query.get(product_id)
    if not product:
        return jsonify({"message": "Product not found"}), 404

    data = request.get_json() or {}
    try:
        rating = int(data.get('rating'))
    except (TypeError, ValueError):
        return jsonify({"message": "Rating must be a whole number between 1 and 5"}), 400

    if rating < 1 or rating > 5:
        return jsonify({"message": "Rating must be between 1 and 5"}), 400

    review = (data.get('review') or '').strip()
    if len(review) > 1000:
        return jsonify({"message": "Review must be 1000 characters or fewer"}), 400

    existing_rating = ProductRating.query.filter_by(user_id=user.id, product_id=product_id).first()
    if existing_rating:
        existing_rating.rating = rating
        existing_rating.review = review
    else:
        db.session.add(ProductRating(user_id=user.id, product_id=product_id, rating=rating, review=review))

    db.session.commit()

    summary = db.session.query(
        func.avg(ProductRating.rating).label('avg_rating'),
        func.count(ProductRating.id).label('rating_count')
    ).filter(ProductRating.product_id == product_id).first()

    return jsonify({
        "message": "Rating saved successfully",
        "product_id": product_id,
        "rating": round(float(summary.avg_rating), 1) if summary.avg_rating is not None else None,
        "rating_count": int(summary.rating_count or 0),
        "user_rating": rating,
        "user_review": review
    }), 200


@app.route('/offers-data')
def get_offers():
    offers = Offer.query.filter_by(is_active=True).order_by(Offer.created_at.desc()).all()
    return jsonify([serialize_offer(offer) for offer in offers])


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


@app.route('/my-orders')
def my_orders():
    user, error = get_authenticated_user(require_admin=False)
    if error:
        return error

    orders = Order.query.filter_by(user_id=user.id).order_by(Order.timestamp.desc()).all()
    return jsonify([serialize_order(order, user) for order in orders])


@app.route('/admin/stats')
def admin_stats():
    admin_user, error = get_authenticated_user(require_admin=True)
    if error:
        return error

    total_revenue = round(db.session.query(func.coalesce(func.sum(Order.total_price), 0)).scalar() or 0, 2)
    total_orders = Order.query.count()
    total_users = User.query.filter_by(is_admin=False).count()
    average_order_value = round((total_revenue / total_orders), 2) if total_orders else 0

    return jsonify({
        "total_users": total_users,
        "total_products": Product.query.count(),
        "total_orders": total_orders,
        "pending_notifications": Order.query.filter_by(admin_notified=False).count(),
        "total_revenue": total_revenue,
        "active_offers": Offer.query.filter_by(is_active=True).count(),
        "average_order_value": average_order_value
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
        total_spend = round(sum(float(order.total_price or 0) for order in orders), 2)
        total_protein_logged = round(sum(float(log.protein_consumed or 0) for log in history), 1)
        last_order = orders[0].timestamp.isoformat() if orders and orders[0].timestamp else None
        payload.append({
            "id": u.id,
            "name": u.name,
            "email": u.email,
            "mobile": u.mobile,
            "weight": u.weight or 0,
            "target": round((u.weight or 0) * (u.goal_multiplier or 1.2), 1),
            "total_spend": total_spend,
            "total_protein_logged": total_protein_logged,
            "order_count": len(orders),
            "last_order_at": last_order,
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


@app.route('/admin/offers')
def get_admin_offers():
    admin_user, error = get_authenticated_user(require_admin=True)
    if error:
        return error

    offers = Offer.query.order_by(Offer.created_at.desc()).all()
    return jsonify([serialize_offer(offer) for offer in offers])


@app.route('/admin/offers', methods=['POST'])
def create_admin_offer():
    admin_user, error = get_authenticated_user(require_admin=True)
    if error:
        return error

    data = request.get_json() or {}
    code = (data.get('code') or '').strip().upper()
    title = (data.get('title') or '').strip()
    discount_type = (data.get('discount_type') or '').strip().lower()

    if not code or not title:
        return jsonify({"message": "Offer code and title are required"}), 400

    if Offer.query.filter_by(code=code).first():
        return jsonify({"message": "Offer code already exists"}), 400

    try:
        discount_value = parse_optional_float(data.get('discount_value'), 'Discount value')
        min_order_amount = parse_optional_float(data.get('min_order_amount'), 'Minimum order amount')
        max_discount = parse_optional_float(data.get('max_discount'), 'Maximum discount')
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 400

    if discount_type and discount_type not in {'percentage', 'fixed', 'free_shipping'}:
        return jsonify({"message": "Discount type is invalid"}), 400

    if discount_type in {'percentage', 'fixed'} and (discount_value is None or discount_value <= 0):
        return jsonify({"message": "Discount value must be greater than 0"}), 400

    if discount_type == 'percentage' and discount_value and discount_value > 100:
        return jsonify({"message": "Percentage discount cannot be more than 100"}), 400

    if min_order_amount is not None and min_order_amount < 0:
        return jsonify({"message": "Minimum order amount cannot be negative"}), 400

    if max_discount is not None and max_discount <= 0:
        return jsonify({"message": "Maximum discount must be greater than 0"}), 400

    condition_text = (data.get('condition_text') or '').strip()
    if not condition_text and discount_type:
        condition_text = build_offer_condition_text(discount_type, discount_value, min_order_amount, max_discount)

    description = (data.get('description') or '').strip()
    if not description and condition_text:
        description = condition_text

    offer = Offer(
        code=code,
        title=title,
        description=description,
        badge=(data.get('badge') or 'Active').strip(),
        cta_note=(data.get('cta_note') or '').strip(),
        discount_type=discount_type or None,
        discount_value=discount_value,
        min_order_amount=min_order_amount,
        max_discount=max_discount,
        condition_text=condition_text,
        is_active=bool(data.get('is_active', True))
    )
    db.session.add(offer)
    db.session.commit()
    return jsonify({"message": "Offer created successfully", "offer": serialize_offer(offer)}), 201


@app.route('/admin/offers/<int:offer_id>', methods=['DELETE'])
def delete_admin_offer(offer_id):
    admin_user, error = get_authenticated_user(require_admin=True)
    if error:
        return error

    offer = Offer.query.get(offer_id)
    if not offer:
        return jsonify({"message": "Offer not found"}), 404

    db.session.delete(offer)
    db.session.commit()
    return jsonify({"message": "Offer removed"}), 200


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
        net_quantity=(data.get('quantity') or '').strip() or None,
        price=float(data.get('price') or 0),
        brand=data.get('brand') or 'NutriCore',
        protein_type=data.get('protein_type') or PROTEIN_TYPE_CONCENTRATE,
        rating=None,
        image_url=normalize_image_url(data.get('image_url'))
    )
    db.session.add(new_product)
    db.session.commit()

    return jsonify({"message": "Product Added!"}), 201


@app.route('/admin/update-product/<int:product_id>', methods=['PUT'])
def update_product(product_id):
    admin_user, error = get_authenticated_user(require_admin=True)
    if error:
        return error

    product = Product.query.get(product_id)
    if not product:
        return jsonify({"message": "Product not found"}), 404

    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({"message": "Product name is required"}), 400

    product.name = name
    product.brand = (data.get('brand') or 'NutriCore').strip() or 'NutriCore'
    product.protein_per_serving = float(data.get('protein') or 0)
    product.net_quantity = (data.get('quantity') or '').strip() or None
    product.price = float(data.get('price') or 0)
    product.protein_type = (data.get('protein_type') or PROTEIN_TYPE_CONCENTRATE).strip() or PROTEIN_TYPE_CONCENTRATE

    image_url = data.get('image_url')
    if image_url is not None:
        product.image_url = normalize_image_url(image_url)

    db.session.commit()
    return jsonify({"message": "Product updated successfully"}), 200


@app.route('/admin/upload-product-image', methods=['POST'])
def upload_product_image():
    admin_user, error = get_authenticated_user(require_admin=True)
    if error:
        return error

    file = request.files.get('image')
    if not file or not file.filename:
        return jsonify({"message": "Please choose an image file"}), 400

    if not is_allowed_image(file.filename):
        return jsonify({"message": "Only JPG, JPEG, PNG, WEBP, or GIF files are allowed"}), 400

    ensure_product_image_dir()
    original_name = secure_filename(file.filename)
    name_root, ext = os.path.splitext(original_name)
    timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    unique_suffix = f"{random.randint(1000, 9999)}"
    saved_name = f"{name_root or 'product'}-{timestamp}-{unique_suffix}{ext.lower()}"
    saved_path = os.path.join(PRODUCT_IMAGE_DIR, saved_name)
    file.save(saved_path)

    return jsonify({
        "message": "Image uploaded successfully",
        "image_url": f"/images/products/uploads/{saved_name}"
    }), 200


@app.route('/admin/delete-product/<int:product_id>', methods=['DELETE'])
def delete_product(product_id):
    admin_user, error = get_authenticated_user(require_admin=True)
    if error:
        return error

    product = Product.query.get(product_id)
    if not product:
        return jsonify({"message": "Product not found"}), 404

    ProductRating.query.filter_by(product_id=product.id).delete()
    db.session.delete(product)
    db.session.commit()
    return jsonify({"message": "Deleted"}), 200


def ensure_schema_compatibility():
    inspector = inspect(db.engine)
    table_names = inspector.get_table_names()

    if 'users' in table_names:
        user_cols = {col['name'] for col in inspector.get_columns('users')}
        if 'is_admin' not in user_cols:
            db.session.execute(text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT FALSE"))
        if 'reset_token' not in user_cols:
            db.session.execute(text("ALTER TABLE users ADD COLUMN reset_token VARCHAR(100) NULL"))
        if 'reset_token_expiry' not in user_cols:
            db.session.execute(text("ALTER TABLE users ADD COLUMN reset_token_expiry DATETIME NULL"))
        if 'mobile' not in user_cols:
            db.session.execute(text("ALTER TABLE users ADD COLUMN mobile VARCHAR(10) NULL"))

    if 'products' in table_names:
        product_cols = {col['name'] for col in inspector.get_columns('products')}
        product_indexes = {idx['name'] for idx in inspector.get_indexes('products')}
        if 'net_quantity' not in product_cols:
            db.session.execute(text("ALTER TABLE products ADD COLUMN net_quantity VARCHAR(50) NULL"))
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
        db.session.execute(text(
            "UPDATE products SET protein_type = 'Whey Protein Concentrate' WHERE protein_type IN ('Whey', 'Mass Gainer')"
        ))
        db.session.execute(text(
            "UPDATE products SET protein_type = 'Whey Protein Isolate' WHERE protein_type = 'Isolate'"
        ))
        db.session.execute(text(
            "UPDATE products SET protein_type = 'Plant-Based Protein' WHERE protein_type = 'Plant'"
        ))
        db.session.execute(text(
            "UPDATE products SET protein_type = 'Casein Protein' WHERE protein_type = 'Casein'"
        ))
        db.session.execute(text(
            "UPDATE products SET protein_type = 'Whey Protein Hydrolysate' WHERE protein_type = 'Hydrolysate'"
        ))

    if 'product_ratings' in table_names:
        rating_cols = {col['name'] for col in inspector.get_columns('product_ratings')}
        rating_indexes = {idx['name'] for idx in inspector.get_indexes('product_ratings')}
        if 'review' not in rating_cols:
            db.session.execute(text("ALTER TABLE product_ratings ADD COLUMN review TEXT NULL"))
        if 'created_at' not in rating_cols:
            db.session.execute(text("ALTER TABLE product_ratings ADD COLUMN created_at DATETIME NULL"))
        if 'updated_at' not in rating_cols:
            db.session.execute(text("ALTER TABLE product_ratings ADD COLUMN updated_at DATETIME NULL"))
        if 'idx_product_ratings_product_id' not in rating_indexes:
            db.session.execute(text("CREATE INDEX idx_product_ratings_product_id ON product_ratings (product_id)"))
        if 'idx_product_ratings_user_id' not in rating_indexes:
            db.session.execute(text("CREATE INDEX idx_product_ratings_user_id ON product_ratings (user_id)"))
        if 'uq_product_ratings_user_product' not in rating_indexes:
            db.session.execute(text("CREATE UNIQUE INDEX uq_product_ratings_user_product ON product_ratings (user_id, product_id)"))

    if 'orders' in table_names:
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

    if 'offers' in table_names:
        offer_cols = {col['name'] for col in inspector.get_columns('offers')}
        if 'badge' not in offer_cols:
            db.session.execute(text("ALTER TABLE offers ADD COLUMN badge VARCHAR(40) NULL"))
        if 'cta_note' not in offer_cols:
            db.session.execute(text("ALTER TABLE offers ADD COLUMN cta_note VARCHAR(160) NULL"))
        if 'discount_type' not in offer_cols:
            db.session.execute(text("ALTER TABLE offers ADD COLUMN discount_type VARCHAR(20) NULL"))
        if 'discount_value' not in offer_cols:
            db.session.execute(text("ALTER TABLE offers ADD COLUMN discount_value FLOAT NULL"))
        if 'min_order_amount' not in offer_cols:
            db.session.execute(text("ALTER TABLE offers ADD COLUMN min_order_amount FLOAT NULL"))
        if 'max_discount' not in offer_cols:
            db.session.execute(text("ALTER TABLE offers ADD COLUMN max_discount FLOAT NULL"))
        if 'condition_text' not in offer_cols:
            db.session.execute(text("ALTER TABLE offers ADD COLUMN condition_text VARCHAR(200) NULL"))
        if 'is_active' not in offer_cols:
            db.session.execute(text("ALTER TABLE offers ADD COLUMN is_active BOOLEAN DEFAULT TRUE"))
        if 'created_at' not in offer_cols:
            db.session.execute(text("ALTER TABLE offers ADD COLUMN created_at DATETIME NULL"))

    db.session.commit()
    ensure_product_image_dir()


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
            "net_quantity": "1kg",
            "price": 68,
            "brand": "Optimum Nutrition",
            "protein_type": PROTEIN_TYPE_CONCENTRATE,
            "rating": 4.8,
            "image_url": "https://images.unsplash.com/photo-1599058917212-d750089bc07e"
        },
        {
            "name": "Dymatize ISO100",
            "protein_per_serving": 25,
            "net_quantity": "900g",
            "price": 72,
            "brand": "Dymatize",
            "protein_type": PROTEIN_TYPE_ISOLATE,
            "rating": 4.7,
            "image_url": "https://images.unsplash.com/photo-1622484212850-eb596d769edc"
        },
        {
            "name": "MyProtein Impact Whey",
            "protein_per_serving": 21,
            "net_quantity": "1kg",
            "price": 52,
            "brand": "MyProtein",
            "protein_type": PROTEIN_TYPE_CONCENTRATE,
            "rating": 4.5,
            "image_url": "https://images.unsplash.com/photo-1579722821273-0f6c7d44362f"
        },
        {
            "name": "BSN Hydro Whey Performance",
            "protein_per_serving": 22,
            "net_quantity": "1.59kg",
            "price": 55,
            "brand": "BSN",
            "protein_type": PROTEIN_TYPE_HYDROLYSATE,
            "rating": 4.6,
            "image_url": "https://images.unsplash.com/photo-1622483767028-3f66f32aef97"
        },
        {
            "name": "Whey Isolate Plus",
            "protein_per_serving": 27,
            "net_quantity": "900g",
            "price": 79,
            "brand": "NutriCore",
            "protein_type": PROTEIN_TYPE_ISOLATE,
            "rating": 4.7,
            "image_url": "https://images.unsplash.com/photo-1549570652-97324981a6fd"
        },
        {
            "name": "Plant Protein Blend",
            "protein_per_serving": 20,
            "net_quantity": "1kg",
            "price": 47,
            "brand": "NutriCore",
            "protein_type": PROTEIN_TYPE_PLANT,
            "rating": 4.4,
            "image_url": "https://images.unsplash.com/photo-1521804906057-1df8fdb718b7"
        },
        {
            "name": "Daily Whey Concentrate",
            "protein_per_serving": 30,
            "net_quantity": "2kg",
            "price": 74,
            "brand": "NutriCore",
            "protein_type": PROTEIN_TYPE_CONCENTRATE,
            "rating": 4.6,
            "image_url": "https://images.unsplash.com/photo-1605296867304-46d5465a13f1"
        },
        {
            "name": "Casein Night Recovery",
            "protein_per_serving": 24,
            "net_quantity": "1kg",
            "price": 63,
            "brand": "NutriCore",
            "protein_type": PROTEIN_TYPE_CASEIN,
            "rating": 4.5,
            "image_url": "https://images.unsplash.com/photo-1574680178050-55c6a6a96e0a"
        }
    ]

    for p in seed_products:
        db.session.add(Product(
            name=p["name"],
            protein_per_serving=p["protein_per_serving"],
            net_quantity=p["net_quantity"],
            price=p["price"],
            brand=p["brand"],
            protein_type=p["protein_type"],
            rating=p["rating"],
            image_url=p["image_url"]
        ))
    db.session.commit()


def seed_offers_if_empty():
    if Offer.query.count() > 0:
        return

    seed_offers = [
        {
            "code": "SAVE10",
            "title": "10% Off Storewide",
            "description": "Get 10% off on your order with a maximum discount of Rs. 400.",
            "badge": "Popular",
            "cta_note": "Best for medium-value supplement orders.",
            "discount_type": "percentage",
            "discount_value": 10,
            "max_discount": 400,
            "condition_text": "10% off up to Rs. 400",
            "is_active": True
        },
        {
            "code": "FIT20",
            "title": "20% Off On Higher Value Carts",
            "description": "Get 20% off on orders above Rs. 3000 for bigger supplement purchases.",
            "badge": "High Value",
            "cta_note": "Ideal for bulk protein and stack combos.",
            "discount_type": "percentage",
            "discount_value": 20,
            "min_order_amount": 3000,
            "condition_text": "20% off on orders above Rs. 3000",
            "is_active": True
        },
        {
            "code": "FREESHIP",
            "title": "Free Shipping Coupon",
            "description": "Remove delivery charges from your order with the free shipping coupon.",
            "badge": "Shipping",
            "cta_note": "Useful for smaller orders where shipping applies.",
            "discount_type": "free_shipping",
            "condition_text": "Free shipping on this order",
            "is_active": True
        }
    ]

    for offer in seed_offers:
        db.session.add(Offer(**offer))
    db.session.commit()


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        ensure_schema_compatibility()
        seed_products_if_empty()
        seed_offers_if_empty()
        ensure_admin_account()

    app.run(debug=True)
