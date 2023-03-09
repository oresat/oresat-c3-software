Engineering Data Link
=====================

General Telecommands
--------------------

+--------------+-----------------+-------------------+---------------+--------------+-------------+------------+
| USLP Primary | Sequence Number | USLP Data Field   | Command Code  | Command Args | HMAC        | USLP FECF  |
| Header       |                 | Field Header      |               |              |             |            |
|              | (4 Octets)      |                   | (1 Octet)     | (X Octets)   | (32 Octets) | (2 Octets) |
| (6 Octets)   +-----------------+ (1 Octet)         +---------------+--------------+             |            |
|              | USLP Transfer   |                   | Payload                      |             |            |
|              | Frame Insert    |                   +---------------+--------------+-------------+            |
|              | Zone            |                   | USLP Transfer Frame Data Zone              |            |
|              |                 +-------------------+--------------------------------------------+            |
|              |                 | USLP Transfer Frame Data Field                                 |            |
+--------------+-----------------+-------------------+--------------------------------------------+------------+
| USLP Transfer Field                                                                                          |
+--------------------------------------------------------------------------------------------------------------+


General Telemetery
------------------

File Transfer
-------------
