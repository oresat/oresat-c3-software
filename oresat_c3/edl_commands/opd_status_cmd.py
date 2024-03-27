import struct

from olaf import logger
from .abc_cmd import AbcCmd

class OpdStatusCmd(AbcCmd):
    id = 13
    req_format = "B"                                                           
    res_format = "B"                                                           
                                                                                
    def __init__(self, node, node_mngr):                     
        self.node = node                                                        
                                                                                
    def run(self, request:bytes) -> bytes:                                      
        logger.info("")
