from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import urllib.parse
from models import db, User

app = Flask(__name__)

password = urllib.parse.quote_plus("journeyBEGINS@1")
app.config['SQLALCHEMY_DATABASE_URI'] = f'mysql+pymysql://root:{password}@localhost/nutricore_db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

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
    
    try:
        db.session.add(new_user)
        db.session.commit()
        return jsonify({"message": "User created successfully!"}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    user = User.query.filter_by(email=data['email']).first()
    
    if user and check_password_hash(user.password_hash, data['password']):
        return jsonify({"message": "Login successful!", "user_id": user.id}), 200
    
    return jsonify({"message": "Invalid credentials"}), 401

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)