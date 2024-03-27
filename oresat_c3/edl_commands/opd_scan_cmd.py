import struct

from olaf import logger
from .abc_cmd import AbcCmd

class OpdScanCmd(AbcCmd):
    id = 9
    req_format = None                                                           
    res_format = "B"                                                          
                                                                                
    def __init__(self, node, node_mngr):                     
        self.node = node                                                        
                                                                                
    def run(self, request:bytes) -> bytes:                                      
        logger.info("")
