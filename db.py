import sqlite3

conn = sqlite3.connect("instance/trackmydeal.db")
cur = conn.cursor()

cur.executescript("""
INSERT INTO pricehistory (product_id, price, price_date)
VALUES 
(4, 240000.0, '2025-09-25 00:00:00'),
(4, 275000.0, '2025-09-26 00:00:00'),
(4, 300000.0, '2025-09-27 00:00:00'),
(4, 245000.0, '2025-09-28 00:00:00'),
(4, 232000.0, '2025-09-29 00:00:00');
""")

conn.commit()
conn.close()
print("Dummy price history inserted successfully.")
