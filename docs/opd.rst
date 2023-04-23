OreSat Power Domain (OPD)
=========================

The OPD allows the C3 to turn other cards on or off, with the exception of the
solar cards.

The solar cards are directly power off the output their solar panels and not 
the batteries.


How The OPD Works
-----------------

Every card, other the solar cards, has a MAX7310 8-pin GPIO expander to control
giving power to the card.

The C3 configures and controls all MAX7310s over I2C, using the pin as describe
below to control the power to all the non-solar cards.


.. autoclass:: oresat_c3.subsystems.opd.OpdPin
   :members:
   :undoc-members:
   :member-order: bysource


.. autoclass:: oresat_c3.subsystems.opd.OpdNodeState
   :members:
   :undoc-members:
   :member-order: bysource
   :exclude-members: from_bytes


Nodes
-----

All Nodes have unique ids.

.. autoclass:: oresat_c3.subsystems.opd.OpdNode
   :members:
   :undoc-members:
   :member-order: bysource
   :exclude-members: from_bytes, is_linux_card
