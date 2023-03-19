import socket
from threading import Thread, Event

from olaf import Resource, logger, TimerLoop

from .. import C3State
from ..ax25 import generate_ax25_packet

BEACON_FIELDS = [
    # C3
    ('APRS', 'Start Chars'),
    ('APRS', 'Satellite ID'),
    ('APRS', 'Beacon Revision'),
    ('C3 State', None),
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

Field location must be list of tuples with one value and None for a Variables at a index or
two values for Variables at a index and subindex.

NOTE: Do not include leading APRS header or trailing CRC32.
'''


class BeaconResource(Resource):

    _DOWNLINK_ADDR = ('localhost', 10015)

    def __init__(self):
        super().__init__()

        logger.info(f'Beacon socket: {self._DOWNLINK_ADDR}')
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # UDP client

    def on_start(self):

        # objects
        self._c3_state_obj = self.node.od['C3 State']
        self._tx_enabled_obj = self.node.od['TX Control']['Enabled']

        # contants
        self._aprs_dest = self.node.od['APRS']['Dest Callsign'].value
        self._aprs_src = self.node.od['APRS']['Src Callsign'].value

        self.node.add_sdo_write_callback(0x8000, self._on_write)

        interval_obj = self.node.od['TX Control']['Beacon Interval']
        self._timer_loop = TimerLoop('beacon', self._send_beacon_thread, interval_obj)
        self._timer_loop.start()

    def on_end(self):

        self._timer_loop.stop()

    def _send_beacon_thread(self) -> bool:

        if self._tx_enabled_obj.value and self._c3_state_obj.value == C3State.BEACON:
            self._send_beacon()

        return True

    def _send_beacon(self):

        payload = bytes()
        for field in BEACON_FIELDS:
            if field[1] is None:
                obj = self.node.od[field[0]]
            else:
                obj = self.node.od[field[0]][field[1]]
            payload += obj.encode_raw(obj.value)

        packet = generate_ax25_packet(
            dest=self._aprs_dest,
            dest_ssid=0,
            src=self._aprs_src,
            src_ssid=0,
            control=0,
            pid=0,
            payload=payload,
            crc32=True
        )

        logger.debug('beaconing')
        self._socket.sendto(packet, self._DOWNLINK_ADDR)

    def _on_write(self, index: int, subindex: int, value):

        self._send_beacon()
