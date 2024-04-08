import struct

from olaf import logger
from .abc_cmd import AbcCmd

class CoSyncCmd(AbcCmd):
    id = 7
    req_format = None                                                           
    res_format = "?"                                                         
                                                                                
    def __init__(self, node, node_mngr):                     
        self.node = node                                                        
                                                                                
    def run(self, request:bytes) -> bytes:
        logger.info("EDL sending CANopen SYNC message")            
        self.node.send_sync()
