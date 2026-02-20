from flask import Flask, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import urllib.parse
import os
from models import db, User, Product, IntakeLog

app = Flask(__name__, static_url_path='', static_folder='static')

raw_password = "journeyBEGINS@1" 
safe_password = urllib.parse.quote_plus(raw_password)

app.config['SQLALCHEMY_DATABASE_URI'] = f'mysql+pymysql://root:{safe_password}@localhost/nutricore_db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    hashed_pw = generate_password_hash(data['password'], method='pbkdf2:sha256')
    new_user = User(
        name=data.get('username') or data.get('name'),
        email=data.get('email'),
        password_hash=hashed_pw,
        weight=data.get('weight'),
        goal_multiplier=data.get('goal_multiplier')
    )
    db.session.add(new_user)
    db.session.commit()
    return jsonify({"message": "User registered successfully!"}), 201

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    user = User.query.filter_by(email=data.get('email')).first()
    if user and check_password_hash(user.password_hash, data.get('password')):
        target = user.weight * user.goal_multiplier
        return jsonify({
            "message": "Login successful!",
            "user_id": user.id,
            "daily_protein_target": target,
            "suggestion": f"To hit your goal, you need {target}g of protein daily."
        }), 200
    return jsonify({"message": "Invalid credentials"}), 401

@app.route('/products', methods=['GET'])
def get_products():
    products = Product.query.all()
    return jsonify([{"id": p.id, "name": p.name, "protein": p.protein_per_serving, "price": p.price} for p in products])

@app.route('/checkout', methods=['POST'])
def checkout():
    data = request.get_json()
    user_id = data.get('user_id')
    product_ids = data.get('product_ids')
    
    total_protein = 0
    total_price = 0
    
    for p_id in product_ids:
        product = Product.query.get(p_id)
        if product:
            total_protein += product.protein_per_serving
            total_price += product.price
            log = IntakeLog(user_id=user_id, product_name=product.name, protein_consumed=product.protein_per_serving)
            db.session.add(log)
    
    db.session.commit()
    
    return jsonify({
        "status": "Payment Successful",
        "invoice": {
            "total_price": total_price,
            "total_protein_gained": total_protein,
            "message": "Invoice sent to registered email."
        }
    }), 200

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)