"""Schedules Windows shutdown at 4:30 AM local time."""
import subprocess
import datetime
import sys

now = datetime.datetime.now()
target = now.replace(hour=4, minute=30, second=0, microsecond=0)
if target <= now:
    target += datetime.timedelta(days=1)

seconds = int((target - now).total_seconds())
print(f"Shutdown scheduled for {target.strftime('%H:%M:%S')} ({seconds}s from now)")

result = subprocess.run(
    ["shutdown", "/s", "/t", str(seconds), "/c", "Cognia manager cycle complete — apagado programado 4:30 AM"],
    capture_output=True, text=True
)
if result.returncode != 0:
    print(f"ERROR: {result.stderr}", file=sys.stderr)
    sys.exit(1)
print("OK — shutdown scheduled.")
