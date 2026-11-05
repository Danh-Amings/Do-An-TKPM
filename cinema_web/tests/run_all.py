"""Chạy toàn bộ bộ kiểm thử:  python tests/run_all.py"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SUITES = ["smoke.py", "test_flows.py", "test_adapter.py", "test_strategy.py", "test_observer.py", "test_state.py"]
bad = []
for name in SUITES:
    r = subprocess.run([sys.executable, os.path.join(HERE, name)], capture_output=True, text=True, encoding="utf-8")
    last = [ln for ln in r.stdout.strip().splitlines() if ln.strip()][-1] if r.stdout.strip() else "(không có đầu ra)"
    ok = r.returncode == 0 and "loi = 0" in last or (r.returncode == 0 and ", 0 lỗi" in last)
    print(("OK   " if ok else "LOI  ") + f"{name:<18} {last.strip('= ')}")
    if not ok:
        bad.append(name)
print("\nTẤT CẢ ĐẠT" if not bad else f"\nCÓ LỖI: {', '.join(bad)}")
sys.exit(1 if bad else 0)
