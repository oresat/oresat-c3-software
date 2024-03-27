import struct

from olaf import logger
from .abc_cmd import AbcCmd

class BeaconPingCmd:
    id = 16
    def unpack(raw:bytes):                                                      
        pass                                                                    
    def run():                                                                  
        pass                                                                    
    def pack() -> bytes:                                                        
        return b''                                                              
                                                                                
def beacon_ping_cmd(raw:bytes) -> bytes:                                                
    def unpack(raw):                                                            
        pass                                         
    def run():                   
        pass                                                                    
    return b''
