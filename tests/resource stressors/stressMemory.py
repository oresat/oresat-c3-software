import socket
import time
import sys

# Targeted at the Flight Software's UDP ingress port.
TARGET_IP = "127.0.0.1"
TARGET_PORT = 10025  
PACKET_SIZE = 1024   # 1KB per packet

def attack():
    print(f"--- STARTING QUEUE FLOOD TEST ---")
    print(f"Target: {TARGET_IP}:{TARGET_PORT}")
    print(f"Goal: Fill the SimpleQueue until MemoryMax=256MB triggers.")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    packets_sent = 0
    mb_sent = 0
    
    try:
        while True:
            payload = b'X' * PACKET_SIZE
            sock.sendto(payload, (TARGET_IP, TARGET_PORT))
            packets_sent += 1
            
            # Progress update every 10MB
            if packets_sent % 10240 == 0:
                mb_sent += 10
                sys.stdout.write(f"\rFlood Volume: {mb_sent} MB sent...")
                sys.stdout.flush()
                # Yield to the scheduler to allow the target app to actually queue the data
                time.sleep(0.001)
                
    except KeyboardInterrupt:
        print("\n\nTest stopped.")
    except Exception as e:
        print(f"\n\nError: {e}")

if __name__ == "__main__":
    attack()