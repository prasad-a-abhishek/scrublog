import time, re, sys, statistics, os
sys.path.insert(0, os.path.abspath("../src"))
from scrublog import clean
ANSI_REGEX = re.compile(r'\x1B(?:[@-Z\\-_]|\\[[0-?]*[ -/]*[@-~])')

text = "\n".join([f"\x1b[32m2026-07-25\x1b[0m \x1b[1mINFO\x1b[0m req={i}" for i in range(5000)])
s_times, r_times = [], []
for _ in range(50):
    t0 = time.perf_counter()
    res = clean(text)
    s_times.append((time.perf_counter() - t0)*1000)
    
    t0 = time.perf_counter()
    res = ANSI_REGEX.sub('', text)
    r_times.append((time.perf_counter() - t0)*1000)

print(f"scrublog: {statistics.mean(s_times):.2f} ms | regex: {statistics.mean(r_times):.2f} ms")
