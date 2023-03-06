import bitstring
import socket
import zlib
from threading import Thread, Event

from olaf import Resource, logger

BEACON_FIELDS = [
    # C3
    ('APRS', 'Start Chars'),
    ('APRS', 'Satellite ID'),
    ('APRS', 'Beacon Revision'),
    ('C3 State'),
    ('C3 Telemetry', 'Uptime'),
    ('APRS', 'Unix Time'),
    ('Persistent State', 'Power Cycles'),
    ('C3 Telemetry', 'eMMC Usage'),
    ('Persistent State', 'LBand RX Bytes'),
    ('Persistent State', 'LBand RX Packets'),
    ('C3 Telemetry', 'LBand RSSI'),
    ('Persistent State', 'UHF RX Bytes'),
    ('Persistent State', 'UHF RX Packets'),
    ('C3 Telemetry', 'UHF RSSI'),
    ('C3 Telemetry', 'Bank State'),
    ('Persistent State', 'EDL Sequence Count'),
    ('Persistent State', 'EDL Rejected Count'),
    # Battery 0
    ('Battery 0', 'VBatt BP1'),
    ('Battery 0', 'VCell BP1'),
    ('Battery 0', 'VCell max BP1'),
    ('Battery 0', 'VCell min BP1'),
    ('Battery 0', 'VCell1 BP1'),
    ('Battery 0', 'VCell2 BP1'),
    ('Battery 0', 'VCell avg BP1'),
    ('Battery 0', 'Temperature BP1'),
    ('Battery 0', 'Temperature avg BP1'),
    ('Battery 0', 'Temperature max BP1'),
    ('Battery 0', 'Temperature min BP1'),
    ('Battery 0', 'Current BP1'),
    ('Battery 0', 'Current avg BP1'),
    ('Battery 0', 'Current max BP1'),
    ('Battery 0', 'Current min BP1'),
    ('Battery 0', 'State BP1'),
    ('Battery 0', 'Reported State of Charge BP1'),
    ('Battery 0', 'Full Capacity BP1'),
    ('Battery 0', 'Reported Capacity BP1'),
    ('Battery 0', 'VBatt BP2'),
    ('Battery 0', 'VCell BP2'),
    ('Battery 0', 'VCell max BP2'),
    ('Battery 0', 'VCell min BP2'),
    ('Battery 0', 'VCell1 BP2'),
    ('Battery 0', 'VCell2 BP2'),
    ('Battery 0', 'VCell avg BP2'),
    ('Battery 0', 'Temperature BP2'),
    ('Battery 0', 'Temperature avg BP2'),
    ('Battery 0', 'Temperature max BP2'),
    ('Battery 0', 'Temperature min BP2'),
    ('Battery 0', 'Current BP2'),
    ('Battery 0', 'Current avg BP2'),
    ('Battery 0', 'Current max BP2'),
    ('Battery 0', 'Current min BP2'),
    ('Battery 0', 'State BP2'),
    ('Battery 0', 'Reported State of Charge BP2'),
    ('Battery 0', 'Full Capacity BP2'),
    ('Battery 0', 'Reported Capacity BP2'),
    # Solar Panel 0
    ('Solar Panel 0', 'Voltage Avg'),
    ('Solar Panel 0', 'Current Avg'),
    ('Solar Panel 0', 'Power Avg'),
    ('Solar Panel 0', 'Voltage Max'),
    ('Solar Panel 0', 'Current Max'),
    ('Solar Panel 0', 'Power Max'),
    ('Solar Panel 0', 'Energy'),
    # Solar Panel 1
    ('Solar Panel 1', 'Voltage Avg'),
    ('Solar Panel 1', 'Current Avg'),
    ('Solar Panel 1', 'Power Avg'),
    ('Solar Panel 1', 'Voltage Max'),
    ('Solar Panel 1', 'Current Max'),
    ('Solar Panel 1', 'Power Max'),
    ('Solar Panel 1', 'Energy'),
    # Solar Panel 2
    ('Solar Panel 2', 'Voltage Avg'),
    ('Solar Panel 2', 'Current Avg'),
    ('Solar Panel 2', 'Power Avg'),
    ('Solar Panel 2', 'Voltage Max'),
    ('Solar Panel 2', 'Current Max'),
    ('Solar Panel 2', 'Power Max'),
    ('Solar Panel 2', 'Energy'),
    # Solar Panel 3
    ('Solar Panel 3', 'Voltage Avg'),
    ('Solar Panel 3', 'Current Avg'),
    ('Solar Panel 3', 'Power Avg'),
    ('Solar Panel 3', 'Voltage Max'),
    ('Solar Panel 3', 'Current Max'),
    ('Solar Panel 3', 'Power Max'),
    ('Solar Panel 3', 'Energy'),
    # Star Tracker
    ('Star Tracker 0', 'Root Partition Percent'),
    ('Star Tracker 0', 'Fread cache length'),
    ('Star Tracker 0', 'Updater Status'),
    ('Star Tracker 0', 'Updates available'),
    ('Star Tracker 0', 'Right Ascension'),
    ('Star Tracker 0', 'Declination'),
    ('Star Tracker 0', 'Roll'),
    ('Star Tracker 0', 'Timestamp Short'),
    # GPS
    ('GPS', 'Root Partition Percent'),
    ('GPS', 'Fread cache length'),
    ('GPS', 'Updater Status'),
    ('GPS', 'Updates available'),
    ('GPS', 'GPS Status'),
    ('GPS', 'Satellites Locked'),
    ('GPS', 'Position X'),
    ('GPS', 'Position Y'),
    ('GPS', 'Position Z'),
    ('GPS', 'Velocity X'),
    ('GPS', 'Velocity Y'),
    ('GPS', 'Velocity Z'),
    ('GPS', 'Timestamp Short'),
    # ACS
    ('ACS', 'Gyro roll'),
    ('ACS', 'Gyro pitch'),
    ('ACS', 'Gyro yaw'),
    ('ACS', 'IMU temp'),
    # DxWiFi
    ('DxWiFi', 'Root Partition Percent'),
    ('DxWiFi', 'Fread cache length'),
    ('DxWiFi', 'Updater Status'),
    ('DxWiFi', 'Updates available'),
    ('DxWiFi', 'Transmitting'),
]
'''
List of OD locations for the beacon fields.

Field location must be list with one value for a Variables at a index or two values for Variables
at a index and subindex.

NOTE: Do not include leading '{{z' or trailing CRC32.
'''


class BeaconResource(Resource):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # UDP client

        self._event = Event()
        self._thread = Thread(target=self._send_beacon_thread)

    def on_start(self):

        self._thread.start()

    def on_end(self):

        self._event.set()
        self._thread.join()

    def _send_beacon_thread(self):

        while not self._event.is_set():
            self._send_beacon()
            self._event.wait(self.od['TX Control']['Beacon Interval'].value / 1000)

    def _send_beacon(self):

        # APRS packet header fields
        dest = self.od['APRS']['Dest Callsign'].value
        dest_ssid = 0
        src = self.od['APRS']['Src Callsign'].value
        src_ssid = 0
        control = 0
        pid = 0

        # callsigns must be 6 chars, add trailing spaces as padding
        src += ' ' * (6 - len(src))
        dest += ' ' * (6 - len(dest))

        # make APRS packet header
        header = dest.encode() + dest_ssid.to_bytes(1, 'little') + \
            src.encode() + src_ssid.to_bytes(1, 'little') + \
            control.to_bytes(1, 'little') + pid.to_bytes(1, 'little')
        header = (bitstring.BitArray(header) << 1).bytes

        packet = bytearray(header)

        # add payload
        for i in BEACON_FIELDS:
            if len(i) == 1:
                obj = self.od[i[0]]
            elif len(i) == 2:
                obj = self.od[i[0]][i[1]]
            packet += obj.encode_raw(obj.value)

        crc32 = zlib.crc32(packet, 0)
        packet += crc32.to_bytes(4, 'little')

        logger.debug('beaconing')
        self._socket.sendto(packet, ('127.0.0.1', 10015))
