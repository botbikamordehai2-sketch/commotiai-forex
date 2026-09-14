import argparse
import sqlite3
import json
from datetime import datetime

DB_PATH = "trinity.db"

# -----------------------------
# ARGUMENTS
# -----------------------------
parser = argparse.ArgumentParser()
parser.add_argument("--append", action="store_true", help="Append snapshot to disk")
parser.add_argument("--write", action="store_true", help="Write snapshot to disk")
args = parser.parse_args()

# -----------------------------
# WRITE MODE
# -----------------------------
if args.write:
    write_mode = "WRITE"
elif args.append:
    write_mode = "APPEND"
else:
    write_mode = "DRY RUN"

# -----------------------------
# DB QUERY HELPER
# -----------------------------
def query(sql, params=()):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]

# -----------------------------
# LOAD DATA FROM DB
# -----------------------------
projects = query("SELECT * FROM projects ORDER BY id")
tasks = query("SELECT * FROM tasks ORDER BY id")
audit = query("SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT 50")

# -----------------------------
# BUILD SNAPSHOT
# -----------------------------
snapshot = {
    "snapshot_id": f"snap_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}",
    "timestamp": datetime.utcnow().isoformat(),
    "total_projects": len(projects),
    "total_tasks": len(tasks),
    "open_tasks": len([t for t in tasks if t["status"] == "pending"]),
    "completed_tasks": len([t for t in tasks if t["status"] == "completed"]),
    "projects": projects,
    "tasks": tasks,
    "audit": audit
}

# -----------------------------
# PRINT AUDIT SUMMARY
# -----------------------------
print("FX STRENGTH SNAPSHOT AUDIT")
print(f"write_mode: {write_mode}")
print(f"projects: {len(projects)}")
print(f"tasks: {len(tasks)}")
print(f"audit_events: {len(audit)}")

# -----------------------------
# WRITE SNAPSHOT TO DISK
# -----------------------------
if write_mode == "WRITE":
    with open("dashboard_snapshot.json", "w") as f:
        json.dump(snapshot, f, indent=4)

    with open("fx_strength_snapshot.json", "w") as f:
        json.dump(snapshot, f, indent=4)

    print("Snapshot written to disk.")

# -----------------------------
# APPEND MODE (OPTIONAL)
# -----------------------------
if write_mode == "APPEND":
    with open("dashboard_snapshot.json", "a") as f:
        f.write("\n")
        json.dump(snapshot, f, indent=4)

    print("Snapshot appended to disk.")

# -----------------------------
# ADD AUDIT LOG ENTRY
# -----------------------------
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
cur.execute(
    "INSERT INTO audit_log (event, project_id) VALUES (?, ?)",
    ("Snapshot generated", None)
)
conn.commit()
conn.close()

print("Audit log updated.")
