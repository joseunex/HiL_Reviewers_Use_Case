#!/usr/bin/env bash
# Clock offsets of the bench with respect to the host, which is its NTP server (Section 7.4.3 of the paper).
#  - Host: state of its chrony (reference of the whole bench).
#  - Raspberry Pi: state of chrony (estimated offset, RMS and corrected drift).
#  - Yún: 10 NTP queries from its Linux side to the host (offset and round trip of each one), with Python 2.
# Usage (on the host, asks for the passwords of the Raspberry Pi and of the Yún):  bash hil_bench/measure_clocks.sh
source "$(dirname "$0")/bench.env"
[ -n "${HOST_IP:-}" ] || { echo "Set HOST_IP in hil_bench/bench.env"; exit 1; }
RPI=${RPI_HOST:?Set RPI_HOST in hil_bench/bench.env}
YUN=${YUN_HOST:-root@arduino.local}
SSHOPT=(-o ConnectTimeout=10 -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa
        -o KexAlgorithms=+diffie-hellman-group14-sha1,diffie-hellman-group1-sha1)
echo "== $(date '+%F %T')"
echo "== Host: chrony"
chronyc tracking 2>&1 | sed -n '1,12p'
echo "== Raspberry Pi ($RPI): chrony"
ssh -o ConnectTimeout=10 "$RPI" 'chronyc tracking; echo; chronyc sourcestats'
echo "== Yún ($YUN): 10 NTP queries to the host"
ssh "${SSHOPT[@]}" "$YUN" "python - $HOST_IP" <<'PY'
import socket, struct, sys, time
HOST = sys.argv[1]
EPOCH = 2208988800
def ntp(b):
    s, f = struct.unpack('!II', b)
    return s - EPOCH + f / 4294967296.0
def query():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(2)
    t1 = time.time()
    s.sendto('\x1b' + 47 * '\0', (HOST, 123))
    d = s.recvfrom(48)[0]
    t4 = time.time()
    s.close()
    t2, t3 = ntp(d[32:40]), ntp(d[40:48])
    return ((t2 - t1) + (t3 - t4)) / 2 * 1000.0, ((t4 - t1) - (t3 - t2)) * 1000.0
res = []
for i in range(10):
    try:
        o, r = query()
        res.append((o, r))
        print('offset %+.2f ms   round trip %.2f ms' % (o, r))
    except Exception as e:
        print('error: %s' % e)
    time.sleep(1)
if res:
    o = sorted(x[0] for x in res); r = sorted(x[1] for x in res)
    print('median: offset %+.2f ms, round trip %.2f ms (offset of the query with the shortest round trip: %+.2f ms)'
          % (o[len(o) // 2], r[len(r) // 2], min(res, key=lambda x: x[1])[0]))
PY
