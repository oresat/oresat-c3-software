import struct

from olaf import logger
from .abc_cmd import AbcCmd

class C3SoftResetCmd(AbcCmd):
    id = 1
    req_format = None                                                           
    res_format = None                                                           
                                                                                
    def __init__(self, node, node_mngr):                     
        self.node = node                                                        
                                                                                
    def run(self, request:bytes) -> bytes:                                      
        logger.info("")
