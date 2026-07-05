import os, psycopg2
url = os.environ["DATABASE_URL"].replace("postgres://", "postgresql://", 1)
conn = psycopg2.connect(url)
cur = conn.cursor()
cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s ORDER BY ordinal_position;", ("pool_pots",))
for row in cur.fetchall():
    print(row[0])
