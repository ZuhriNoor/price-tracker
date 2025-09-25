import sqlite3
import pandas as pd

conn = sqlite3.connect("instance/trackmydeal.db")

df = pd.read_sql_query("", conn)
print(df)

conn.close()