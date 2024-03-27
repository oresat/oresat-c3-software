import struct

from olaf import logger
from .abc_cmd import AbcCmd

class C3HardResetCmd(AbcCmd):                                                           
    id = 2                                                                    
    req_format = None                                                           
    res_format = None                                                           
                                                                                
    def __init__(self, node, node_mngr):                     
        self.node = node                                                        
                                                                                
    def run(self, request:bytes) -> bytes:                                      
        logger.info("EDL hard reset")                                           
        self.node.stop(NodeStop.HARD_RESET) 
