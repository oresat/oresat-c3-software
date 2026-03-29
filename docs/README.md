# Documentation Index

This directory contains the primary documentation and final reporting for the OreSat C3 Scheduling Optimization project.

## Core Project Documentation

### Final Project Report
The comprehensive summary of the independent study, including executive summary, learning objectives, detailed chronological logs, hardware results, and self-grading discussion.

### The Scheduler Bible
The technical documentation for future OreSat engineers. It details the process classification tiers, resource budget math, systemd dependency graphs, and known architectural trade-offs like the "Bulkhead Paradox."

## supporting

Detailed technical reports generated during the discovery and design phases of the project can be found in the Supporting Documents folder. This includes:

#### State Analysis: Process Inventory & Source Code Audit

An initial audit of the OreSat Linux App Framework (OLAF). It identifies independent Linux processes, classifies internal Python threads by criticality, and documents the initial risks associated with GIL starvation and hardware watchdog timing.

#### Data Flow Mapping, IPC Analysis, and Vulnerability Determination

A deep dive into how data moves through the C3 card. This document maps external UDP sockets (Uplink/Downlink/Safety) and internal thread-based message passing via SimpleQueue. it formally defines the "Infinite Queue" and "Blocking I/O" scenarios as mission-critical vulnerabilities.

#### Resource Budget & Systemd Design

The foundation for the "Resource Cage." It details the investigation into Cgroups v2 controllers and establishes the 1GB RAM budget—specifically the decision to reserve ~600MB for the Kernel Page Cache to mitigate flash storage latency.

#### Scheduling Architecture Implementation

The technical log of the transition from design to active system configuration. It includes the logic behind the oresat-watchdog.service Real-Time settings and the oresat-c3.service resource limits required for development.

#### Environment Setup Log

A chronological record of establishing the OreSat development environment. It documents the installation of oresat-configs and oresat-c3-software, as well as the technical challenges and resolutions regarding custom WSL2 kernel compilation and Virtual CAN (vcan) support.