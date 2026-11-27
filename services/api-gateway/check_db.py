import sqlite3
db = r'D:\ai项目\enterprise-ai-app\services\api-gateway\data\enterprise_ai.db'
conn = sqlite3.connect(db)
cur = conn.cursor()
cur.execute('SELECT id, title FROM conversations LIMIT 5')
for row in cur.fetchall():
    title = row[1]
    print(f"Title: [{repr(title)}] Bytes: {title.encode('utf-8')}")
conn.close()
