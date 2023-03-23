Engineering Data Link
=====================

General Telecommands
--------------------

Packet Stucture
***************

+--------------+-----------------+-------------------+---------------+--------------+-------------+------------+
| USLP Primary | Sequence Number | USLP Data Field   | Command Code  | Command Args | HMAC        | USLP FECF  |
| Header       |                 | Header            |               |              |             |            |
|              | (4 Octets)      |                   | (1 Octet)     | (X Octets)   | (32 Octets) | (2 Octets) |
| (7 Octets)   +-----------------+ (1 Octet)         +---------------+--------------+             |            |
|              | USLP Transfer   |                   | Payload                      |             |            |
|              | Frame Insert    |                   +---------------+--------------+-------------+            |
|              | Zone            |                   | USLP Transfer Frame Data Zone              |            |
|              |                 +-------------------+--------------------------------------------+            |
|              |                 | USLP Transfer Frame Data Field                                 |            |
+--------------+-----------------+-------------------+--------------------------------------------+------------+
| USLP Transfer Field                                                                                          |
+--------------------------------------------------------------------------------------------------------------+

EDL Codes
*********

.. autoclass:: oresat_c3.protocals.edl.EdlCode
   :members:
   :undoc-members:
   :member-order: bysource
   :exclude-members: from_bytes, to_bytes

File Transfer
-------------
