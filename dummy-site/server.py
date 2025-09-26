from flask import Flask, jsonify, request, send_from_directory, abort
import json
import os

app = Flask(__name__, static_folder=None) # We will handle static files manually
PRICES_FILE = 'prices.json'

# --- HTML Serving Routes ---

@app.route('/')
def home():
    return send_from_directory('.', 'home.html')

@app.route('/watch')
def watch_page():
    return send_from_directory('.', 'watch.html')

@app.route('/earbuds')
def earbuds_page():
    return send_from_directory('.', 'earbuds.html')

# This route is needed to serve images like watch.png
@app.route('/<path:filename>')
def static_files(filename):
    # Serve common image types or other static files
    if filename.endswith(('.png', '.jpg', '.jpeg', '.gif')):
        return send_from_directory('.', filename)
    abort(404)


# --- API Routes for Price Management ---

@app.route('/api/price/<product_id>', methods=['GET'])
def get_price(product_id):
    """Reads the price from the JSON file."""
    if not os.path.exists(PRICES_FILE):
        return jsonify({"error": "Prices file not found"}), 404
    with open(PRICES_FILE, 'r') as f:
        prices = json.load(f)
    price = prices.get(product_id)
    if price is None:
        return jsonify({"error": "Product not found"}), 404
    return jsonify({"price": price})

@app.route('/api/price/<product_id>', methods=['POST'])
def update_price(product_id):
    """Updates the price in the JSON file."""
    data = request.get_json()
    new_price = data.get('price')

    if new_price is None or not isinstance(new_price, (int, float)):
        return jsonify({"error": "Invalid price"}), 400

    if not os.path.exists(PRICES_FILE):
        return jsonify({"error": "Prices file not found"}), 404

    with open(PRICES_FILE, 'r+') as f:
        prices = json.load(f)
        if product_id not in prices:
            return jsonify({"error": "Product not found"}), 404
        
        prices[product_id] = float(new_price)
        f.seek(0) # Rewind to the beginning of the file
        json.dump(prices, f, indent=2)
        f.truncate() # Remove trailing data if the new file is shorter

    return jsonify({"success": True, "new_price": new_price})

if __name__ == '__main__':
    print("Starting local TestMart server at http://127.0.0.1:5001")
    app.run(port=5001, debug=True)
