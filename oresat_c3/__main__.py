import os

from olaf import olaf_setup, olaf_run, app, rest_api, render_olaf_template
from flask import Flask, render_template, jsonify, request, send_from_directory
from spacepackets.uslp.header import SourceOrDestField
import socket


from . import __version__
from .subsystems.opd import Opd
from .subsystems.fram import Fram
from .services.beacon import BeaconService
from .services.edl import EdlService
from .services.opd import OpdService
from .services.state import StateService
from .protocols.edl import EdlCode, edl_parameter_types, EdlClient
import struct



@rest_api.app.route('/beacon')
def beacon_template():
    return render_olaf_template('beacon.html', name='Beacon')

@rest_api.app.route('/edl')
def edl_template():
    return render_olaf_template('edl.html', name='EDL (Engineering Data Link)')

@rest_api.app.route('/static/edl/c3-cmd/<code>/', methods=['POST'])
def edl_change(code):
    try:
        code = int(code)
        option = EdlCode(code)
    except ValueError:
        return  jsonify({'Error' : f'invalid code: {code}'}), 400 
     
    try:
        # Retrieve data from the form
        data = request.json
        args = data.get('args', [])

    except Exception as e:
        error_message = str(e)
        return jsonify({"error": error_message}), 400
    
    # Check to see if the num of args is correct for the code
    if len(args) != len(edl_parameter_types[code]):
        return jsonify(f'Incorrect number of args for {option}')
    
    parameter_types = edl_parameter_types[code]
    payload = struct.pack('<B', code)   # Assume code is uint8

    for i, param_type in enumerate(parameter_types):
        if param_type == bool:
            payload += struct.pack('<?', args[i])
        elif param_type == int:
            payload += struct.pack('<i', args[i])
        else:  # Type is bytes
            # Process bytes here if needed
            pass

        
    # Create a UDP socket
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # Send the message
    udp_socket.sendto(EdlClient._generate_packet(payload, SourceOrDestField(1)), EdlClient.EdlService._UPLINK_ADDR)

    # Close the socket
    udp_socket.close()

    response_data = {"message": "Request fulfilled"}
    return jsonify(response_data), 200


@rest_api.app.route('/opd')
def opd_template():
    return render_olaf_template('opd.html', name='OPD (OreSat Power Domain)')


@rest_api.app.route('/state')
def state_template():
    return render_olaf_template('state.html', name='State')


def main():

    path = os.path.dirname(os.path.abspath(__file__))

    args = olaf_setup(f'{path}/data/oresat_c3.dcf', master_node=True)
    mock_args = [i.lower() for i in args.mock_hw]
    mock_opd = 'opd' in mock_args or 'all' in mock_args
    mock_fram = 'fram' in mock_args or 'all' in mock_args

    app.node.od['Manufacturer software version'].value = __version__

    # TODO get from OD
    i2c_bus_num = 2
    opd_enable_pin = 20
    fram_i2c_addr = 0x50

    opd = Opd(opd_enable_pin, i2c_bus_num, mock=mock_opd)
    fram = Fram(i2c_bus_num, fram_i2c_addr, mock=mock_fram)

    app.add_service(StateService(fram))  # add state first to restore state from F-RAM
    app.add_service(BeaconService())
    app.add_service(EdlService(opd))
    app.add_service(OpdService(opd))

    rest_api.add_template(f'{path}/templates/beacon.html')
    rest_api.add_template(f'{path}/templates/edl.html')
    rest_api.add_template(f'{path}/templates/opd.html')
    rest_api.add_template(f'{path}/templates/state.html')

    # on factory reset clear F-RAM
    app.set_factory_reset_callback(fram.clear)

    olaf_run()


if __name__ == '__main__':
    main()
