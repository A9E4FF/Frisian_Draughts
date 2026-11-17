"""Deterministic adversarial Hub peer; never used as a rules oracle."""
import sys
import time

scenario = sys.argv[1]
searching = False


def emit(line):
    if scenario == 'fragmented':
        data = (line + '\r\n').encode()
        for offset in range(0, len(data), 3):
            sys.stdout.buffer.write(data[offset:offset + 3])
            sys.stdout.buffer.flush()
    else:
        print(line, flush=True)


for line in sys.stdin:
    command = line.split()[0]
    if command == 'hub':
        if scenario == 'stderr':
            sys.stderr.write('diagnostic\n' * 50000)
            sys.stderr.flush()
        if scenario == 'oversized':
            emit('id name=' + 'x' * 8192)
        if scenario == 'misleading-handshake':
            emit('info message="wait ready"')
            continue
        emit('id name="Fake Hub Engine" version=1')
        emit('param name=variant value=frisian type=enum values=frisian')
        emit('future-command field="safe to ignore"')
        emit('wait')
    elif command == 'init':
        emit('ready')
    elif command == 'go':
        searching = True
        if scenario == 'crash':
            sys.exit(7)
        if scenario == 'malformed':
            emit('info pv="unfinished')
        elif scenario == 'error':
            emit('error message="invalid position"')
        elif scenario == 'missing-done' or scenario == 'stop':
            pass
        else:
            emit('info depth=1 score=0.08 nodes=42 time=0.001 pv="31-26 16-21"')
            emit('done' if scenario == 'terminal' else 'done move=31-26 ponder=16-21')
            if scenario == 'duplicate':
                emit('done move=16-21')
            searching = False
    elif command == 'stop' and searching:
        if scenario != 'missing-done':
            emit('done move=31-26')
            searching = False
    elif command == 'ping':
        emit('pong')
    elif command == 'quit':
        if scenario == 'ignore-quit':
            time.sleep(30)
        break
