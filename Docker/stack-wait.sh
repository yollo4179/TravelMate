#!/usr/bin/env bash
set -euo pipefail
python3 - "${STACK_WAIT_TIMEOUT:-600}" <<'PY'
import json
import subprocess
import sys
import time

names = ['travel-postgres', 'travelmate-redis', 'travelmate-server', 'travelmate-embedding']
deadline = time.monotonic() + float(sys.argv[1])
last = {}
while True:
    states = {}
    for name in names:
        result = subprocess.run(['docker', 'inspect', '--format', '{{json .State}}', name],
                                capture_output=True, text=True)
        if result.returncode:
            states[name] = 'missing'
        else:
            state = json.loads(result.stdout)
            states[name] = state.get('Health', {}).get('Status', state['Status']) if state['Running'] else state['Status']
    if states != last:
        print(' | '.join(f'{name}: {status}' for name, status in states.items()), flush=True)
        last = states
    if all(value == 'healthy' for value in states.values()):
        print('All four services passed Docker healthchecks.', flush=True)
        break
    if any(value in {'exited', 'dead', 'missing'} for value in states.values()):
        raise SystemExit('Required container is not running. Inspect startup errors before retrying.')
    if time.monotonic() >= deadline:
        raise SystemExit('Readiness timed out; not all required services are healthy.')
    time.sleep(2)
PY
