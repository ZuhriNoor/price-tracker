from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
import requests
import re
from apscheduler.schedulers.background import BackgroundScheduler
from playwright.sync_api import sync_playwright
from random import randint

# -------------------- Flask app setup --------------------
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "change-this-secret")
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///trackmydeal.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

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
    status = db.Column(db.String(50))  # "pending" or "sent"

class Comparison(db.Model):
    __tablename__ = "comparison"
    comparison_id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.product_id"), nullable=False)
    platform = db.Column(db.String(50))
    product_url = db.Column(db.Text, nullable=False)
    added_date = db.Column(db.DateTime, default=datetime.utcnow)

# -------------------- Playwright Scraper --------------------
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/140.0.7339.129 Safari/537.36"
}

def scrape_price_playwright(url):
    """Scrape title and price using Playwright (robust for Amazon)"""
    from playwright.sync_api import sync_playwright
    import re

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=60000)
            page.wait_for_load_state("networkidle")
            
            # Wait extra just in case Amazon dynamically loads price
            page.wait_for_timeout(3000)

            # Try selectors first
            price_selectors = [
                "#priceblock_ourprice",
                "#priceblock_dealprice",
                "#priceblock_saleprice",
                "span.a-price > span.a-offscreen",
                "span.a-price-whole"
            ]

            price = None
            for selector in price_selectors:
                el = page.query_selector(selector)
                if el:
                    price_text = el.inner_text().replace("₹", "").replace(",", "").strip()
                    if price_text:
                        try:
                            price = float(price_text)
                            break
                        except:
                            continue

            # Fallback to regex on whole page if no selector worked
            if price is None:
                text = page.inner_text("body")
                match = re.search(r"(?:₹|Rs\.?)\s?[\d,]+(?:\.\d{1,2})?", text)
                if match:
                    price = float(match.group(0).replace("₹", "").replace("Rs", "").replace(".", "").replace(",", "").strip())

            # Extract title (first long line in body text)
            text = page.inner_text("body")
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            title = None
            for line in lines:
                if len(line) > 15:
                    title = line
                    break

            browser.close()
            return price, url, title

    except Exception as e:
        print("Playwright scrape error:", e)
        return None, url, None

# -------------------- Scheduler Job --------------------
SCHEDULER_INTERVAL_MINUTES = int(os.environ.get('POLL_MINUTES', 30))

def poll_all_products():
    with app.app_context():
        print('[scheduler] Polling products for price updates at', datetime.utcnow())
        products = Product.query.all()
        
        for prod in products:
            try:
                # Scrape current price using your existing Playwright function
                price, _, _ = scrape_price_playwright(prod.url)
                
                if price is not None:
                    # 1. Update Product.current_price
                    prod.current_price = price
                    
                    # 2. Add a new row in PriceHistory
                    db.session.add(PriceHistory(product_id=prod.product_id, price=price))
                    
                    # 3. Commit changes to database
                    db.session.commit()
                    
                    print(f"[scheduler] Updated '{prod.product_name}' to ₹{price}")
                else:
                    print(f"[scheduler] Price not found for '{prod.product_name}'")
                    
            except Exception as e:
                print(f"[scheduler] Error updating product {prod.product_id}: {e}")


# -------------------- Scheduler Setup --------------------

# Set interval (minutes) — you can change for testing
SCHEDULER_INTERVAL_MINUTES = 180  # for testing, you can set 1

# Initialize scheduler
scheduler = BackgroundScheduler()

# Add the polling job
scheduler.add_job(
    func=poll_all_products,            # function to run
    trigger='interval',                 # run periodically
    minutes=SCHEDULER_INTERVAL_MINUTES,# interval in minutes
    id='poller',                        # job id
    replace_existing=True               # replace if already exists
)

# Function to start scheduler
def start_scheduler():
    try:
        scheduler.start()
        print(f'[scheduler] Started successfully, polling every {SCHEDULER_INTERVAL_MINUTES} minutes')
    except Exception as e:
        print('[scheduler] Could not start scheduler:', e)

# Start the scheduler
start_scheduler()

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
        try: threshold = float(request.form.get('threshold', 0))
        except: threshold = 0.0
        name = request.form.get('name')

        price, final_url, title = scrape_price_playwright(url)
        new_product = Product(
            product_name=name if name else title,
            url=final_url if final_url else url,
            user_id=user_id,
            target_price=threshold,
            current_price=price
        )
        db.session.add(new_product)
        db.session.flush()
        if price is not None:
            db.session.add(PriceHistory(product_id=new_product.product_id, price=price))
            db.session.commit()
            flash(f"✅ {new_product.product_name} added! Current price ₹{price}.", "success")
        else:
            db.session.commit()
            flash("⚠️ Product added, initial price fetch failed.", "warning")
        return redirect(url_for('track'))

    products = Product.query.filter_by(user_id=user_id).all()
    return render_template('track.html', products=products)

@app.route('/trend', methods=['GET','POST'])
def trend():
    if 'user' not in session:
        return redirect(url_for('login'))
    user_id = session['user']
    products = Product.query.filter_by(user_id=user_id).all()
    return render_template('trend.html', products=products)

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
    if not os.path.exists('trackmydeal.db'):
        with app.app_context():
            db.create_all()
    start_scheduler()
    app.run(debug=True)
