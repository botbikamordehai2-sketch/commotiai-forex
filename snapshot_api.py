from fastapi import FastAPI
import sqlite3

app = FastAPI()

DB_PATH = "trinity.db"

def query(sql, params=()):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/snapshot")
def get_snapshot():
    projects = query("SELECT * FROM projects ORDER BY id")
    tasks = query("SELECT * FROM tasks ORDER BY id")
    audit = query("SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT 50")

    return {
        "projects": projects,
        "tasks": tasks,
        "audit": audit,
        "total_projects": len(projects),
        "total_tasks": len(tasks),
        "open_tasks": len([t for t in tasks if t['status'] == 'pending']),
        "completed_tasks": len([t for t in tasks if t['status'] == 'completed'])
    }
