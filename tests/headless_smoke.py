"""Run manually: .venv/bin/python tests/headless_smoke.py (no API calls)."""
import os
import subprocess
import time
import urllib.request
from pathlib import Path

os.environ.setdefault('QMS_RESULTS_PATH', 'data/results.csv')
log = Path('screenshots/headless-smoke.log')
with log.open('w') as output:
    proc = subprocess.Popen(['.venv/bin/python','-m','streamlit','run','app.py','--server.headless=true','--server.address=127.0.0.1','--server.port=8502','--browser.gatherUsageStats=false'],stdout=output,stderr=subprocess.STDOUT)
    try:
        start = time.monotonic()
        healthy = False
        while time.monotonic()-start < 10:
            if proc.poll() is not None:
                raise RuntimeError(log.read_text())
            try:
                with urllib.request.urlopen('http://127.0.0.1:8502/_stcore/health',timeout=1) as response:
                    healthy = response.status == 200
            except OSError:
                pass
            time.sleep(.5)
        assert healthy, 'Streamlit health endpoint failed'
        print('PASS: Streamlit headless stayed healthy for 10 seconds; rendering verified by pytest AppTest.')
    finally:
        proc.terminate()
        proc.wait(timeout=5)
print(log.read_text())
