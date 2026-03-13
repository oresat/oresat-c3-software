import socket
import time

# For baseline jitter testing. 
# It removes application-level variables by sending a simple 1Hz pulse.

UDP_IP = "127.0.0.1"
UDP_PORT = 10015

print(f"Starting Pure Beacon (1Hz) on {UDP_IP}:{UDP_PORT}")
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

while True:
    try:
        sock.sendto(b"HEARTBEAT", (UDP_IP, UDP_PORT))
    except Exception as e:
        print(f"Socket Error: {e}")
    time.sleep(1.0)