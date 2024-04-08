import struct

from olaf import logger
from .abc_cmd import AbcCmd

class C3FactoryResetCmd(AbcCmd):                                
    id = 3
    req_format = None                                                           
    res_format = None                                                           
                                                                                
    def __init__(self, node, node_mngr):                     
        self.node = node                                                        
                                                                                
    def run(self, request:bytes) -> bytes:                                      
        logger.info("EDL factory reset")
        self.node.stop(NodeStop.FACTORY_RESET)
