import urllib.parse
from sqlalchemy import Column, Integer, String, Float, ForeignKey, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# 1. HANDLE SPECIAL CHARACTERS IN PASSWORD
# Your password has an '@', so we must encode it
raw_password = "journeyBEGINS@1" 
safe_password = urllib.parse.quote_plus(raw_password)

# 2. DATABASE CONNECTION SETUP
# Using the encoded password and the correct database name
DATABASE_URL = f"mysql+pymysql://root:{raw_password}@localhost:3306/nutricore_db"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- DATABASE TABLES (MODELS) ---

# 3. USER TABLE
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50))
    weight = Column(Float)
    # goal_multiplier: 1.2 (Sedentary), 1.5 (Active), 1.8 (Athlete)
    goal_multiplier = Column(Float)

# 4. PRODUCT TABLE
class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100))
    protein_per_serving = Column(Float)
    price = Column(Float)

# 5. INTAKE LOG TABLE
class IntakeLog(Base):
    __tablename__ = "intake_logs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    product_name = Column(String(100))
    protein_consumed = Column(Float)