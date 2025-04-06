C3 State
========

The C3's main state machine

States
------

- ``OFFLINE``: This state is never actually reachable by the device. Reset vector is ``PRE_DEPLOY``.
- ``PRE_DEPLOY``: Holding state after deployment of satellite but before deployment of antennas.
  Ensures a minimum amount of time passes before attempting to deploy antennas and going active.
- ``DEPLOY``: Antenna deployment state. Attempts to deploy antennas several times before moving to
  Standby.
- ``STANDBY``: Satellite is functional but in standby state. Battery level is too low or tx is
  disabled.
- ``BEACON``: Active beaconing state. Broadcasts telemetry packets via radio periodically.
- ``EDL``: Currently receiving and/or transmitting engineering data link packets with a ground
  station.

State Machine
-------------

For specific timeouts and delays values, see the ``od.yaml`` file.

.. note:: State is periodically save to F-RAM and before a reset. On a reset, the last state will
   be the initial state.

.. mermaid::

    stateDiagram-v2
        OFFLINE --> PRE_DEPLOY: Powered on with a cleared F-RAM
        PRE_DEPLOY --> DEPLOY: After a timeout and a good battery level
        DEPLOY --> STANDBY: After multiple deploy attempts with a short delay between each
        STANDBY --> BEACON: Tx is enabled and battery level is good
        STANDBY --> EDL: On a valid EDL telecommand
        EDL --> BEACON: After a timeout when Tx is enabled and battery level is good
        BEACON --> EDL: On a valid EDL telecommand
        EDL --> STANDBY: After a timeout when Tx is disabled or low battery level
        BEACON --> STANDBY: After a timeout or low battery level
