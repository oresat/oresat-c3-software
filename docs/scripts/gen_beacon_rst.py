#!/usr/bin/env python3

import sys
from os.path import dirname, abspath

from eds_utils.core.file_io.read_eds import read_eds
from eds_utils.core import DataType

# add parent dir of file dir to path
_FILE_PATH = dirname(abspath(__file__ + '/../..'))
sys.path.insert(0, _FILE_PATH)

from oresat_c3.resources.beacon import BEACON_FIELDS


def gen_beacon_rst():
    '''
    Generate the beacon rst file from Python code and eds file.
    '''

    eds, _ = read_eds(_FILE_PATH + '/oresat_c3/data/oresat_c3.eds')

    data = []
    data.append((0, 'APRS: Header', DataType.OCTET_STRING.name, 16,
                 'See the bitshifted header definition above'))
    offset = 16

    for field in BEACON_FIELDS:
        for index in eds.indexes:
            index_obj = eds[index]
            if index_obj.parameter_name != field[0]:
                continue

            name = index_obj.parameter_name
            if field[1] is None:
                if index_obj.data_type == DataType.VISIBLE_STRING:
                    size = len(index_obj.default_value)
                else:
                    size = index_obj.data_type.size // 8
                data.append((offset, name, index_obj.data_type.name, size, index_obj.comments))
                offset += size
            else:
                for subindex in index_obj.subindexes:
                    subindex_obj = index_obj[subindex]
                    if subindex_obj.parameter_name != field[1]:
                        continue

                    name += f': {subindex_obj.parameter_name}'
                    if subindex_obj.data_type == DataType.VISIBLE_STRING:
                        size = len(subindex_obj.default_value)
                    else:
                        size = subindex_obj.data_type.size // 8
                    data.append((offset, name, subindex_obj.data_type.name, size,
                                 subindex_obj.comments))
                    offset += size
                    break
            break

    data.append((offset, 'APRS: CRC32', DataType.UNSIGNED32.name, 4, 'packet checksum'))
    offset += 4

    lines = []
    lines.append('Beacon\n')
    lines.append('======\n')
    lines.append('\n')
    lines.append('OreSat use AX.25 V2 frame for it\'s beacon format.\n')
    lines.append('\n')
    lines.append('A great reference for AX.25 is at '
                 'https://notblackmagic.com/bitsnpieces/ax.25/\n')
    lines.append('\n')
    lines.append('Beacon AX.25 Header Definition\n')
    lines.append('------------------------------\n')
    lines.append('\n')
    lines.append('.. note:: The AX.25 header is bitshifted to the left by one bit.\n')
    lines.append('\n')
    lines.append('+------------------+-----------------------------------+----------+-------------'
                 '----------------------+-----------+---------+-----+\n')
    lines.append('|                  | Src Callsign                      | Src SSID | Dest Callsig'
                 'n                     | Dest SSID | Control | PID |\n')
    lines.append('+------------------+-----+-----+-----+-----+-----+-----+----------+-----+-----+-'
                 '----+-----+-----+-----+-----------+---------+-----+\n')
    lines.append('| Value            | "O" | "R" | "E" | "S" | "A" | "T" | 0        | "S" | "P" | '
                 '"A" | "C" | "E" | " " | 0         | 0       | 0   |\n')
    lines.append('+------------------+-----+-----+-----+-----+-----+-----+----------+-----+-----+-'
                 '----+-----+-----+-----+-----------+---------+-----+\n')
    lines.append('| Hex              | 4F  | 52  | 45  | 53  | 41  | 54  | 00       | 53  | 50  | '
                 '41  | 43  | 45  | 20  | 00        | 00      | 00  |\n')
    lines.append('+------------------+-----+-----+-----+-----+-----+-----+----------+-----+-----+-'
                 '----+-----+-----+-----+-----------+---------+-----+\n')
    lines.append('| Hex (bitshifted) | 9E  |68   | 5A  | 6A  | 52  | 6C  | 00       | 6A  | 64  | '
                 '52  | 56  | 5A  | 28  | 00        | 00      | 00  |\n')
    lines.append('+------------------+-----+-----+-----+-----+-----+-----+----------+-----+-----+-'
                 '----+-----+-----+-----+-----------+---------+-----+\n')
    lines.append('| Octet Offset     | 0   | 1   | 2   | 3   | 4   | 5   | 6        | 7   | 8   | '
                 '9   | 10  | 11  | 12  | 13        | 14      | 15  |\n')
    lines.append('+------------------+-----+-----+-----+-----+-----+-----+----------+-----+-----+-'
                 '----+-----+-----+-----+-----------+---------+-----+\n')
    lines.append('\n')
    lines.append('\n')
    lines.append('Beacon Definition\n')
    lines.append('-----------------\n')
    lines.append('\n')
    lines.append(f'Beacon total length: {offset} octets\n')
    lines.append('\n')
    lines.append('.. csv-table::\n')
    lines.append('    :header: "Offset", "Name", "Data Type", "Octets", "Comments"\n')
    lines.append('    :widths: 5, 30, 10, 5, 50\n')
    lines.append('\n')
    for i in data:
        comments = i[4].replace('\n', '\n    ')  # fix for multi-line comments
        lines.append(f'    "{i[0]}", "{i[1]}", "{i[2]}", "{i[3]}", "{comments}"\n')

    with open(f'{_FILE_PATH}/docs/beacon.rst', 'w') as f:
        f.writelines(lines)


if __name__ == '__main__':
    gen_beacon_rst()
