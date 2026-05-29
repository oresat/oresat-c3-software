import socket
import time
import statistics
import csv
import argparse
import os

# Configuration
BEACON_PORT = 10015
LISTEN_IP = "0.0.0.0"
BUFFER_SIZE = 4096

def analyze_jitter(duration_seconds=60, output_file="jitter_data.csv"):
    """
    Listens for UDP beacons, calculates arrival jitter, and logs stats.
    Includes socket reuse to prevent port collisions on quick restarts.
    """
    if os.path.exists(output_file):
        base, ext = os.path.splitext(output_file)
        counter = 1
        while os.path.exists(output_file):
            output_file = f"{base}_{counter}{ext}"
            counter += 1

    print(f"--- STARTING JITTER ANALYSIS ---")
    print(f"Listening on {LISTEN_IP}:{BEACON_PORT}")
    print(f"Duration: {duration_seconds} seconds")
    print(f"Output: {output_file}")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, 'SO_REUSEPORT'):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        
    sock.bind((LISTEN_IP, BEACON_PORT))
    sock.setblocking(False)
    
    start_time = time.time()
    packet_times = []
    deltas = []
    
    try:
        while (time.time() - start_time) < duration_seconds:
            try:
                data, addr = sock.recvfrom(BUFFER_SIZE)
                arrival_time = time.time()
                packet_times.append(arrival_time)
                
                if len(packet_times) > 1:
                    delta_ms = (packet_times[-1] - packet_times[-2]) * 1000.0
                    deltas.append(delta_ms)
                    print(f"Beacon Recv! Delta: {delta_ms:.2f} ms")
                else:
                    print(f"Beacon Recv! (Establishing baseline)")
                    
            except BlockingIOError:
                time.sleep(0.001)
                continue
            except Exception as e:
                print(f"Error: {e}")
                break
                
    except KeyboardInterrupt:
        print("\nStopping early...")
        
    print("\n--- ANALYSIS COMPLETE ---")
    if len(deltas) < 2:
        print("Insufficient data.")
        return

    mean_int = statistics.mean(deltas)
    std_jitter = statistics.stdev(deltas)
    
    print(f"Total Packets: {len(packet_times)}")
    print(f"Mean Interval: {mean_int:.2f} ms")
    print(f"Std Dev (Jitter): {std_jitter:.2f} ms")
    
    with open(output_file, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=['packet_index', 'arrival_timestamp', 'delta_ms'])
        writer.writeheader()
        for i in range(1, len(packet_times)):
            writer.writerow({
                'packet_index': i,
                'arrival_timestamp': f"{packet_times[i]:.6f}",
                'delta_ms': f"{deltas[i-1]:.4f}"
            })
    print(f"Saved to {output_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='OreSat Jitter Analyzer')
    parser.add_argument('--seconds', type=int, default=60)
    parser.add_argument('--out', type=str, default='jitter_results.csv')
    args = parser.parse_args()
    analyze_jitter(args.seconds, args.out)