import time
import sys

def log(msg):
    print(msg, flush=True)

log("Armed. Triggering leak in 5s...")
time.sleep(5)

leaked_memory = []
try:
    for i in range(1, 1000):
        # bytearray(5MB) + write loop forces kernel to assign physical RAM (RSS)
        chunk = bytearray(5 * 1024 * 1024)
        
        for j in range(0, len(chunk), 4096):
            chunk[j] = 1 # Write to every memory page
        leaked_memory.append(chunk)
        
        if i % 10 == 0:
            log(f"Consumed {i*5} MB of Resident RAM...")
        time.sleep(0.05)

except Exception as e:
    log(f"Process terminated or error occurred: {e}")