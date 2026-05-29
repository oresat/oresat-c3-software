# Validation & Stress Testing Tools

This directory contains the scripts used to verify the performance and resilience of the updated C3 Scheduling Architecture.

## 1. Metric Collection

### ```measureJitter.py```

#### Function: 
Listens for UDP beacons on port 10015 and calculates the microsecond-precision delta between packet arrivals.

#### Goal: 
Proves that telemetry pulses remain consistent (low jitter) even when the system is under extreme load.

### Usage:
    python3 measureJitter.py --seconds 600 --out results.csv

## 2. Resource Stressors

These scripts simulate worst-case software failures to test the kernel's response.

### ```stressCPU.py```

#### Function: 
Spawns rogue processes to saturate all available CPU cores with infinite arithmetic loops.

#### Goal: 
Verifies that the Watchdog (Priority 99) and Flight Software (Weight 500) successfully preempt background noise and maintain execution.

### ```stressMemory.py```

#### Function: 
Floods the flight software's UDP ingress port (10025) with a high-volume stream of 1KB packets.

#### Goal: 
Simulates a radio/network flood to trigger the "Infinite Queue" scenario, testing the MemoryMax resource limit.

### ```memoryBomb.py```

#### Function: 
Memory allocator that writes to bytearray buffers to force Resident Set Size (RSS) accounting.

#### Goal: 
Tries to trigger the Linux OOM (Out of Memory) Killer to prove the "Resource Cage" effectively isolates memory leaks and prevents system-wide crashes.

## 3. Deployment & Testing Helpers

### ```pureBeacon.py```

#### Function: 
A "Pure" 1Hz UDP beacon generator.

#### Goal: 
Used for baseline testing to remove the confounding variables of theflight software stack.

### ```modeController.sh```

#### Function: 
A Bash shell script that automates the transition between testing modes.

#### Goal: 
Reconfigures the oresat-c3.service to run either the production software, the OOM validation bomb, or the beacon test.

#### Usage:

    chmod +x modeController.sh
    ./modeController.sh {oom|pure|restore}

## 4. Analysis Tools

Scripts used to transform raw data into visuals and stats.

### ```analysis/compareJitter.py```

#### Function: 
Analyze legacy and optimized CSV files from the *results/jitter/* and *results/initial_validation* folder.

#### Goal: 
Produces a summary table (Mean, StdDev, Max Spike) and a comparative boxplot illustrating how the optimization eliminates timing spikes during CPU saturation.

#### Usage:

    python3 analysis/compareJitter.py

### ```analysis/IOSaturationAnalysis.py```

#### Function:

Analyze transient and sustained IO saturation CSV files from the *results/stability* folder.

#### Goal:

Produces  a Distribution Curve (probability density) and a 10-Packet Rolling Jitter plot. This proves that timing standard deviation remains flat and does not degrade during sustained storage I/O blocks.

#### Usage:

    python3 analysis/IOSaturationAnalysis.py
