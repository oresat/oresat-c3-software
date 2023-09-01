import os

from olaf import olaf_setup, olaf_run, app, rest_api, render_olaf_template
from flask import Flask, render_template, jsonify, request, send_from_directory
from spacepackets.uslp.header import SourceOrDestField
import socket

from . import __version__
from .subsystems.opd import Opd
from .subsystems.fram import Fram, FramKey
from .services.beacon import BeaconService
from .services.edl import EdlService
from .services.opd import OpdService
from .services.state import StateService
from .protocols.edl_command import EdlCommandCode, EdlCommandRequest, edl_parameter_types
from .protocols.edl_packet import EdlPacket, SourceOrDestField



@rest_api.app.route('/beacon')
def beacon_template():
    return render_olaf_template('beacon.html', name='Beacon')

@rest_api.app.route('/edl')
def edl_template():
    return render_olaf_template('edl.html', name='EDL (Engineering Data Link)')

DOWNLINK_ADDR = ('localhost', 10025)
UPLINK_ADDR = ('localhost', 10016)

# Set by main, global to allow endpoint functions access to HMAC
fram = None

@rest_api.app.route('/static/edl/c3-cmd/<code>/', methods=['POST'])
def edl_change(code):
    try:
        code = int(code)
        option = EdlCommandCode(code)
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

    # Verify that types are correct
    for i, param_type in enumerate(parameter_types):
        if param_type == "bool" and type(args[i]) == bool:
            continue
        elif param_type == "int" and type(args[i]) == int:
            continue
        elif param_type == "bytes" and type(args[i]) == str:
            # Todo: Cast the string to the type specified in oresat-configs
            return jsonify('failed to send EDL request, SDO writes are not implemented yet'), 500
        else:  
            return jsonify(f'failed to send EDL request, incorrect argument type, {args[i]} should be type {param_type}'), 500

    global fram
    packer = EdlPacket(EdlCommandRequest(option, tuple(args)), fram[FramKey.EDL_SEQUENCE_COUNT], SourceOrDestField.SOURCE)
    downlink_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    uplink_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    uplink_socket.bind(UPLINK_ADDR)
    uplink_socket.settimeout(1)

    # Send the message
    try:
       downlink_socket.sendto(packer.pack(fram[FramKey.CRYTO_KEY]), DOWNLINK_ADDR)
    except Exception as e:
        return jsonify(f'failed to send EDL request: {e}'), 500

    # Await a response
    try:
        res_message, _ = uplink_socket.recvfrom(1024)
    except socket.timeout:
        return jsonify('Oresat failed to respond'), 500

    res_packet = EdlPacket.unpack(fram[FramKey.CRYTO_KEY], res_message)
    
    # Close the socket
    uplink_socket.close()
    downlink_socket.close()

    return jsonify(res_packet.payload.values), 200


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
    global fram 
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
