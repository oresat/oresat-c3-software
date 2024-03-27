import struct

from olaf import logger
from .abc_cmd import AbcCmd

class OpdProbeCmd(AbcCmd):
    id = 10
    req_format = "B"                                                          
    res_format = "?"                                                           
                                                                                
    def __init__(self, node, node_mngr):                     
        self.node = node                                                        
                                                                                
    def run(self, request:bytes) -> bytes:                                      
        logger.info("")
