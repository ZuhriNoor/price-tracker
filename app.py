from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
import traceback
import time
import random
import hashlib
import json
import re
from dotenv import load_dotenv

# ADDED: Imports for new logic
import google.generativeai as genai   # ✅ same import
from playwright.sync_api import sync_playwright
from apscheduler.schedulers.background import BackgroundScheduler

# -------------------- ENVIRONMENT --------------------
load_dotenv()

# -------------------- Flask app setup --------------------
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "change-this-secret")
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///trackmydeal.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# -------------------- Gemini Configuration --------------------
# ❌ OLD CODE (remove this):
# genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
# model = genai.GenerativeModel("gemini-2.5-flash")

# ✅ NEW CODE:
api_key = os.environ.get("GOOGLE_API_KEY")
if not api_key:
    print("--- IMPORTANT: GOOGLE_API_KEY not set in .env ---")
    client = None
    model_name = None
else:
    try:
        genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
        model = genai.GenerativeModel("gemini-2.5-flash")
    except Exception as e:
        print(f"--- IMPORTANT: Gemini API not configured. Please set GOOGLE_API_KEY. Error: {e} ---")
        model = None

# -------------------- MODELS --------------------
class User(db.Model):
    __tablename__ = 'user'
    user_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(50), default='user')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    products = db.relationship('Product', backref='owner', lazy=True)

class Product(db.Model):
    __tablename__ = "products"
    product_id = db.Column(db.Integer, primary_key=True)
    product_name = db.Column(db.String(255))
    url = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.user_id'), nullable=False)
    target_price = db.Column(db.Float, nullable=False)
    current_price = db.Column(db.Float)
    added_date = db.Column(db.DateTime, default=datetime.utcnow)
    price_history = db.relationship("PriceHistory", backref="product", lazy=True)
    alerts = db.relationship("Alert", backref="product", lazy=True)
    comparisons = db.relationship("Comparison", backref="product", lazy=True)

class PriceHistory(db.Model):
    __tablename__ = "pricehistory"
    history_id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.product_id"), nullable=False)
    price = db.Column(db.Float, nullable=False)
    price_date = db.Column(db.DateTime, default=datetime.utcnow)

class Alert(db.Model):
    __tablename__= "alert"
    alert_id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.product_id"), nullable=False)
    alert_date = db.Column(db.DateTime, default=datetime.utcnow)
    price_at_alert = db.Column(db.Float)
    status = db.Column(db.String(50))

class Comparison(db.Model):
    __tablename__ = "comparison"
    comparison_id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.product_id"), nullable=False)
    platform = db.Column(db.String(50))
    product_url = db.Column(db.Text, nullable=False)
    added_date = db.Column(db.DateTime, default=datetime.utcnow)

# -------------------- Scraper + Gemini Logic --------------------
def clean_price(price_str: str) -> float | None:
    """Utility to convert price string from Gemini to float."""
    if not price_str or not isinstance(price_str, str):
        return None
    try:
        cleaned = re.sub(r"[₹,]", "", price_str).strip()
        return float(cleaned)
    except (ValueError, TypeError):
        return None

def extract_with_gemini(image_bytes: bytes) -> dict:
    """Extracts data from a screenshot using Gemini."""
    if not model:
        print("Gemini model not initialized. Skipping extraction.")
        return {"title": None, "price": None}
    try:
        response = model.generate_content([
            {"mime_type": "image/png", "data": image_bytes},
            "Extract the product name and price from this screenshot. "
            "Return as strict JSON with keys: 'title' and 'price'. Do not use markdown."
        ])
        text = response.text.strip().replace("```json", "").replace("```", "")
        data = json.loads(text)
        return data
    except Exception as e:
        print(f"Gemini extraction failed: {e}")
        return {"title": None, "price": None, "raw": response.text if 'response' in locals() else 'No response'}

def fetch_product_data(url: str, max_retries: int = 3) -> dict:
    """Fetches screenshot and extracts data using Gemini with backoff."""
    delay = 1.0
    for attempt in range(1, max_retries + 1):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False, args=["--no-sandbox"])
                context = browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                )
                page = context.new_page()
                page.goto(url, timeout=30000)
                page.wait_for_load_state("domcontentloaded", timeout=20000)
                time.sleep(2)

                image = page.screenshot(clip={
                    "x": 200,
                    "y": 200,
                    "width": 600,
                    "height": 450
                })
                browser.close()

                data = extract_with_gemini(image)
                return {
                    "title": data.get("title"),
                    "price": clean_price(data.get("price")),
                    "url": url
                }
        except Exception as e:
            print(f"[Attempt {attempt}] Playwright failed for {url}: {e}")
            if attempt < max_retries:
                sleep_time = delay + random.uniform(0, delay * 0.5)
                print(f"Retrying in {sleep_time:.2f}s...")
                time.sleep(sleep_time)
                delay *= 2
            else:
                print("Max retries exceeded.")
    return {"title": None, "price": None, "url": url}

# -------------------- Scheduler --------------------
def poll_all_products():
    with app.app_context():
        print(f'[Scheduler] Polling products for price updates at {datetime.utcnow()}')
        products = Product.query.all()

        for prod in products:
            try:
                data = fetch_product_data(prod.url)
                price = data.get("price")

                if price is not None:
                    prod.current_price = price
                    db.session.add(PriceHistory(product_id=prod.product_id, price=price))
                    if price <= prod.target_price:
                        existing_alert = Alert.query.filter_by(product_id=prod.product_id, status="pending").first()
                        if not existing_alert:
                            db.session.add(Alert(product_id=prod.product_id, price_at_alert=price, status="pending"))
                            print(f"[Scheduler] !!! PRICE ALERT for '{prod.product_name}' !!!")

                    db.session.commit()
                    print(f"[Scheduler] Updated '{prod.product_name}' to ₹{price}")
                else:
                    print(f"[Scheduler] Price not found for '{prod.product_name}'")
            except Exception as e:
                db.session.rollback()
                print(f"[Scheduler] Error updating product {prod.product_id}: {e}")

SCHEDULER_INTERVAL_MINUTES = 10
scheduler = BackgroundScheduler()
scheduler.add_job(
    func=poll_all_products,
    trigger='interval',
    minutes=SCHEDULER_INTERVAL_MINUTES,
    id='poller',
    replace_existing=True
)
def start_scheduler():
    try:
        scheduler.start()
        print(f'[scheduler] Started successfully, polling every {SCHEDULER_INTERVAL_MINUTES} minutes')
    except Exception as e:
        print('[scheduler] Could not start scheduler:', e)

# -------------------- Routes --------------------
@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = generate_password_hash(request.form['password'])
        if User.query.filter_by(email=email).first():
            flash('User already exists. Try logging in.')
            return redirect(url_for('login'))
        user = User(name=name, email=email, password=password)
        db.session.add(user)
        db.session.commit()
        flash('Account created. Please log in.')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            session['user'] = user.user_id
            return redirect(url_for('menu'))
        flash('Invalid credentials')
        return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/menu')
def menu():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('menu.html')

@app.route('/track', methods=['GET','POST'])
def track():
    if 'user' not in session:
        return redirect(url_for('login'))
    user_id = session['user']

    if request.method == 'POST':
        url = request.form.get('url')
        try:
            threshold = float(request.form.get('threshold', 0))
        except (ValueError, TypeError):
            threshold = 0.0
        
        print(f"Fetching data for URL: {url}")
        data = fetch_product_data(url)
        price = data.get("price")
        title = data.get("title")

        if not title:
            flash("❌ Could not extract product details. Please check the URL.", "error")
            return redirect(url_for('track'))

        new_product = Product(
            product_name=title,
            url=url,
            user_id=user_id,
            target_price=threshold,
            current_price=price
        )
        db.session.add(new_product)
        db.session.flush()

        if price is not None:
            db.session.add(PriceHistory(product_id=new_product.product_id, price=price))
            flash(f"✅ '{new_product.product_name}' added! Current price is ₹{price}.", "success")
        else:
            flash(f"⚠️ '{new_product.product_name}' added, but we couldn't fetch the initial price.", "warning")
        
        db.session.commit()
        return redirect(url_for('track'))

    products = Product.query.filter_by(user_id=user_id).all()
    return render_template('track.html', products=products)

# In your app.py file

@app.route('/trend', methods=['GET','POST'])
def trend():
    if 'user' not in session:
        return redirect(url_for('login'))
        
    user_id = session['user']
    products = Product.query.filter_by(user_id=user_id).all()
    selected_product_id = None

    if request.method == 'POST':
        # Get the product ID from the submitted form
        product_id = request.form.get('product_id')
        if product_id:
            selected_product_id = int(product_id)
    
    return render_template(
        'trend.html', 
        products=products, 
        selected_product_id=selected_product_id
    )

@app.route('/trend_data/<int:product_id>')
def trend_data(product_id):
    ph = PriceHistory.query.filter_by(product_id=product_id).order_by(PriceHistory.price_date.asc()).all()
    data = [{'date': p.price_date.isoformat(), 'price': p.price} for p in ph]
    return jsonify(data)

@app.route('/compare')
def compare():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('compare.html')

# -------------------- Main --------------------
if __name__ == '__main__':
    with app.app_context():
        if not os.path.exists('trackmydeal.db'):
            db.create_all()
            print("Database created.")
    start_scheduler()
    app.run(debug=True, use_reloader=False)
