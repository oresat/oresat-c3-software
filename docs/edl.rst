Engineering Data Link
=====================

.. note:: Octets are used instead of bytes as octets are guaranteed to be 8 bits and bytes are not.

The main form of communication between OreSat and UniClOGS is thru the EDL (Engineering Data Link).

The EDL has Uplink and Downlink.


.. mermaid::

   flowchart LR
      oresat[OreSat]
      uniclogs[UniClOGS]

      uniclogs -.-> |EDL UHF Uplink| oresat
      uniclogs -.-> |EDL L Band Uplink| oresat
      oresat -.-> |EDL UHF Downlink| uniclogs


EDL Packet Structure
--------------------

The EDL uses USLP (Unified Space Link Protocol) from CCSDS (The Consultative Committee for Space Data Systems).

+--------------+---------------------+-----------------+------------+-------------------+------------+
| USLP Primary | Sequence Number     | USLP Data Field | Payload    | HMAC              | USLP FECF  |
| Header       |                     | Header          |            |                   |            |
|              | (4 Octets)          |                 | (X Octets) | (32 Octets)       | (2 Octets) |
| (7 Octets)   |                     | (1 Octet)       +------------+-------------------+            |
|              |                     |                 | USLP Transfer Frame Data Zone  |            |
|              +---------------------+-----------------+--------------------------------+            |
|              | USLP Transfer Frame | USLP Transfer Frame Data Field                   |            |
|              | Insert Zone         |                                                  |            |
+--------------+---------------------+--------------------------------------------------+------------+
| USLP Transfer Frame                                                                                |
+----------------------------------------------------------------------------------------------------+

USLP Primary Header
*******************

- **Transfer Frame Version Number**: 4 bits. Always ``"C"`` in ASCII.
- **Space Craft ID**: 16 bits: Always ``"OS"`` in ASCII (short for OreSat) .
- **Source or Destination Identifier**: 1 bit. Source (aka ``0b1``) is for UniClOGS and destination
  (aka ``0b0``) is for OreSat.
- **Virtual Channel ID`**: 6 bits.
   - Virtual channel ``0b000000`` is used for C3 commands.
   - Virtual channel ``0b000001`` is used for file transfer.
- **MAP ID: 6 bits**. Not used by OreSat (will always be ``0b000000``).
- **End of Frame Primary Header Flag**: 1 bit. Always ``0b0``.
- **Frame Length**: 16 bits. Length of entire packet **minus** one, in octets.
- **Bypass / Sequence Control Flag**: 1 bit. Is set to ``0b0`` to mark the packet is sequence
  controlled QoS will Frame Accepts Check of the FARM will not be bypassed.
- **Protocol Control Command Flag**: 1 bit. Will be set to ``0b0`` to mark the TFDF is user data
  and not protocol controlled information, aka the packet contains a EDL payload.
- **Reserve spare bits**: 2 bits.
- **OCF (Operation Control Field) Flag**: 1 bit. Set to ``0b0``, to mark the OCF is not included in packet.
- **VC Frame Count Length**: 3 bits. Is set to ``0b000`` for no VCF Count bits.

Sequence Number
***************

The sequence number is used to prevent repeat attacks. Is a 32-bit unsigned integer.

On every received packet, the C3 will increment its count. Any EDL packet received must have a
higher number that the C3 internal count, otherwise the C3 will ignore it. Number rolls over at
``FF FF FF FF``.

The sequence number will full take up the optional TFIZ (Transfer Frame Insert Zone) part of the
USLP Transfer Frame.

USLP Data Field Header
**********************

- TFDZ Construction Rules: 3 bits. Set to ``0b111`` to mark variable length TFDZ that is not
  segmented.
- UPID (USLP Protocol Identifier): 5 bits. Set to ``0b000101`` to mark the protocol in the TFDZ
  is mission specific.

  - See https://sanaregistry.org/r/uslp_protocol_id/ for all definitions.

Payload
*******

Differs between types. Length can differ, but it will always be at least 1 octet. If there is
no payload, there is no reason for the EDL packet.

HMAC
****

32 octets HMAC used for authentication. If the HMAC fails, the packet will be rejected and no response
will be sent back. For HMAC basics, see https://en.wikipedia.org/wiki/HMAC.

FECF (Frame Error Control Field)
********************************

For packet checking. Will be CRC16 (Cyclic redundancy check - length 16 bits) checksum of the rest
of the packet. For CRC basics, see https://en.wikipedia.org/wiki/Cyclic_redundancy_check.

EDL C3 Command Packet
-----------------------

The payload of EDL Packet with C3 command will have 1 octet to defined which code it and
arbitrary octets for data.

.. autoclass:: oresat_c3.protocols.edl_command.EdlCommandCode
   :members:
   :undoc-members:
   :member-order: bysource

EDL File Transfer Packet
------------------------

The EDL uses CCSDS File Delivery Protocol (CFDP) for file transfer. The CCSDS PDU packets will be
used as the payload of the main USLP packet.

References
----------

- `Overview of Space Packet Protocols Green Book - CCSDS 130.0-G-4 <https://public.ccsds.org/Pubs/130x0g4.pdf>`_
- `USLP Blue Book - CCSDS 732.1-B-2 <https://public.ccsds.org/Pubs/732x1b2.pdf>`_
- `CFPD Blue Book - CCSDS 727.0-B-5 <https://public.ccsds.org/Pubs/727x0b5.pdf>`_
