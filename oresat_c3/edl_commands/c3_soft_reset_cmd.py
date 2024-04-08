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
        enable, = struct.unpack(req_format, request)
        
        logger.info("EDL soft reset")
        self.node.stop(NodeStop.SOFT_RESET)
        
        return struct.pack(res_format, ret)

