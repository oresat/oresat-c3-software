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
It uses SDLS (Space Data Link Security) for authentication and COP-1 (Communication Operation Procedure-1) for
frame retransmission.

+--------------+---------------------+-----------------+---------------------+--------------+---------------+------------+
| USLP Primary | SDLS header         | USLP Data Field | Payload             | SDLS Trailer | Operational   | USLP FECF  |
| Header       |                     | Header          |                     |              | Control Field |            |
|              | (6 Octets)          |                 | (X Octets)          | (32 Octets)  |               | (2 Octets) |
| (7 Octets)   |                     | (1 Octet)       +---------------------+              | (0/4 Octets)  |            |
|              |                     |                 | USLP Transfer Frame |              |               |            |
|              |                     |                 | Data Zone           |              |               |            |
|              +---------------------+-----------------+---------------------+              |               |            |
|              | USLP SDLS Header    | USLP Transfer Frame Data Field        |              |               |            |
|              | (uses insert zone)  |                                       |              |               |            |
+--------------+---------------------+---------------------------------------+--------------+---------------+------------+
| USLP Transfer Frame                                                                                                    |
+------------------------------------------------------------------------------------------------------------------------+

USLP Primary Header
*******************

- **Transfer Frame Version Number**: 4 bits. Always ``"C"`` in ASCII.
- **Space Craft ID**: 16 bits: Always ``"OS"`` in ASCII (short for OreSat).
- **Source or Destination Identifier**: 1 bit. Source (aka ``0b1``) is for UniClOGS and destination
  (aka ``0b0``) is for OreSat.
- **Virtual Channel ID**: 6 bits.
   - Virtual channel ``0b000000`` is used for C3 commands.
   - Virtual channel ``0b000001`` is used for file transfer.
   - Virtual channel ``0b000010`` is an IDLE channel carrying frames with CLCWs, but no payload or SDLS.
- **MAP ID: 4 bits**. Not used by OreSat (will always be ``0b0000``).
- **End of Frame Primary Header Flag**: 1 bit. Always ``0b0``.
- **Frame Length**: 16 bits. Length of entire packet **minus** one, in octets.
- **Bypass / Sequence Control Flag:** 1 bit.
   - ``0b0`` for Sequence Controlled Service (guaranteed in-order delivery).
   - ``0b1`` for Expedited Service (bypass the FARM-1 Frame Acceptance Check, delivery not guaranteed).
- **Protocol Control Command Flag**: 1 bit.
   - ``0b0`` marks the TFDF as a Protocol Control Command (for COP-1).
   - ``0b1`` marks the TFDF as user data (an EDL payload).
- **Reserve spare bits**: 2 bits.
- **OCF (Operational Control Field) Flag**: 1 bit. If set, the OCF is included in packet.
- **VC Frame Count Length**: 3 bits. Is set to ``0b000`` for no VCF Count bits.

SDLS Header
***********

- **Security Parameter Index**: 16 bits. A value of 1 indicates that the frame uses the oresat
  sdls implemenation.
- **Sequence Number**: 32 bits. The sequence number is described below.

The sequence number is used to prevent repeat attacks. Is a 32-bit unsigned integer.

On every received packet, the C3 will increment its count. Any EDL packet received must have a
higher number that the C3 internal count, otherwise the C3 will ignore it. Number rolls over at
``FF FF FF FF``.

Though out of spec, the SDLS Header is currently implemented using the USLP insert zone.

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

VCID 2 is a special exception: it is an "idle" service which does not carry any useful data in the
payload (a single empty octet). Instead, the frames contain CLCWs to prevent the COP-1 service from timing out.

SDLS Trailer
************

32 octets HMAC used for authentication. If the HMAC fails, the packet will be rejected and no response
will be sent back. For HMAC basics, see https://en.wikipedia.org/wiki/HMAC.

Though out of spec, the SDLS Trailer is currently inserted into the end of data zone.

Operational Control Field
*************************

4 octets. The Operational Control Field is used by COP-1 to transfer Communications Link Control
Words (CLCWs). These carry COP-1 status data for the receiving end, and must be received within
FOP-1's timeout (default every 3 seconds). Note that the CLCW Protocol Data Unit is defined in the
standard for the TC Space Data Link Protocol, not COP-1.

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
- `COP-1 Blue Book - CCSDS 232.1-B-2 <https://ccsds.org/Pubs/232x1b2e2c1.pdf>`_
- `TC Space Data Link Protocol Blue Book - CCSDS 232.0-B-4 <https://ccsds.org/Pubs/232x0b4e1c1.pdf>`_
