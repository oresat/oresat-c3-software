import struct

from olaf import logger
from .abc_cmd import AbcCmd

class CoNodeEnableCmd(AbcCmd):
    id = 4
    req_format = "B?"                                                          
    res_format = "B"                                                           
                                                                                
    def __init__(self, node, node_mngr):                     
        self.node = node                                                        
                                                                                
    def run(self, request:bytes) -> bytes:                                      
        logger.info(f"EDL enabling CANopen node {name} (0x{node_id:02X})")
