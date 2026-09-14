import re
from collections import Counter

with open("d1_scheduler.log", encoding="utf-8", errors="replace") as f:
    lines = f.readlines()

lock_busy = [l for l in lines if "API_LOCK_BUSY" in l]
scan_started = [l for l in lines if "D1 scan started" in l]
scan_completed = [l for l in lines if "D1 scan completed" in l]
saved_signals = [l for l in lines if "Saved signals_1d.csv" in l]
errors = [l for l in lines if re.search(r"\bERROR\b", l)]
lock_acquired = [l for l in lines if "LOCK_ACQUIRED" in l]
lock_released = [l for l in lines if "LOCK_RELEASED" in l]

print(f"Total log lines:              {len(lines)}")
print(f"D1 scan started events:       {len(scan_started)}")
print(f"D1 scan completed events:     {len(scan_completed)}")
print(f"Saved signals_1d.csv events:  {len(saved_signals)}")
print(f"API_LOCK_BUSY skip events:    {len(lock_busy)}")
print(f"LOCK_ACQUIRED events:         {len(lock_acquired)}")
print(f"LOCK_RELEASED events:         {len(lock_released)}")
print(f"ERROR events:                 {len(errors)}")

print("\n--- API_LOCK_BUSY occurrences (timestamps) ---")
for l in lock_busy:
    print(l.strip())

print("\n--- ERROR occurrences (first 20) ---")
for l in errors[:20]:
    print(l.strip())

print("\n--- D1 scan started (first 5, last 5) ---")
for l in scan_started[:5]:
    print(l.strip())
print("...")
for l in scan_started[-5:]:
    print(l.strip())