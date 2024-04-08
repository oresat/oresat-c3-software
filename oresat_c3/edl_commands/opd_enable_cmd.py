import struct

from olaf import logger
from .abc_cmd import AbcCmd

class OpdEnableCmd(AbcCmd):
    id = 11
    req_format = "B?"     
    res_format = "B"   
                                                                          
    def __init__(self, node, node_mngr):
        self.node = node                
                                                                                
    def run(self, request:bytes) -> bytes:
        logger.info("")
