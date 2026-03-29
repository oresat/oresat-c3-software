import multiprocessing
import time
import sys

def waste_cpu():
    """
    Infinite arithmetic loop to pin a single CPU core at 100%.
    """
    while True:
        _ = 999 * 999

def attack():
    print(f"--- STARTING CPU STRESS TEST ---")
    core_count = multiprocessing.cpu_count()
    print(f"Detected {core_count} CPU cores. Spawning rogue processes...")
    print(f"GOAL: Verify oresat-watchdog (Priority 99) stays active.")
    
    processes = []
    
    try:
        # Spawn a rogue process for every core
        for i in range(core_count):
            p = multiprocessing.Process(target=waste_cpu)
            p.daemon = True 
            p.start()
            processes.append(p)
            
        print("\nSystem should now be at 100% CPU Load.")
        
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nStopping stress test...")
        for p in processes:
            if p.is_alive():
                p.terminate()
        print("Cleanup complete.")

if __name__ == "__main__":
    attack()