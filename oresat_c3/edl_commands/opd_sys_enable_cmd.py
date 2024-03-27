import struct

from olaf import logger
from .abc_cmd import AbcCmd

class OpdSysEnableCmd(AbcCmd):
    id = 8
    req_format = "?"                                                           
    res_format = "?"                                                           
                                                                                
    def __init__(self, node, node_mngr):                     
        self.node = node                                                        
                                                                                
    def run(self, request:bytes) -> bytes:                                      
        logger.info("")
