C3 State
========

The C3's main state machine

States
------

.. autoclass:: oresat_c3.C3State
   :members:
   :undoc-members:
   :member-order: bysource
   :exclude-members: from_char, to_char


State Machine
-------------

For specific timeouts and delays values, see the ``oresat_c3.dcf`` file.

.. note:: State is periodically save to F-RAM. On a reset, the last state will be
   the initial state.

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
