import os

MOCK_HW = os.environ.get('MOCK_HW', 'true').lower() != 'false'
I2C_BUS_NUM = int(os.environ.get('I2C_BUS_NUM', '2'))
FRAM_ADDR = int(os.environ.get('FRAM_ADDR', '0x50'), 16)
