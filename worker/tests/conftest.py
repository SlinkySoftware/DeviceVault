import os
import tempfile

# The worker app creates its identity at import time; keep it out of the real
# state directory. Must run before any devicevault_worker module is imported.
os.environ['DV_STATE_DIR'] = tempfile.mkdtemp(prefix='dv-worker-tests-')
