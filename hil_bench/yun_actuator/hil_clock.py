import sys, time
# Installed at /root/hil_clock.py on the Linux side of the Arduino Yun by prepare_yun.sh.
# For every line received on stdin it answers the system time (Unix epoch) in milliseconds.
# The sketch starts it through the Bridge and uses it to synchronise the clock of the microcontroller,
# because the BusyBox date of the Yun does not support %N and only gives seconds.
while True:
    line = sys.stdin.readline()
    if not line:
        break
    sys.stdout.write("%d\n" % int(time.time() * 1000))
    sys.stdout.flush()
