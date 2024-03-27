import struct

from olaf import logger
from .abc_cmd import AbcCmd

class PingCmd(AbcCmd):
    id = 17
    req_format = "I"                                                           
    res_format = "I"                                                      
                                                                                
    def __init__(self, node, node_mngr):                     
        self.node = node                                                        
                                                                                
    def run(self, request:bytes) -> bytes:                                      
        logger.info("")
