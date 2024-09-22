# Abstract Base Class for EDL commands

from abc import ABC, abstractmethod

from olaf import MasterNode
from services.node_manager import NodeManagerService


class AbcCmd(ABC):
    id = None
    req_format = None
    res_format = None

    def __init__(self, node: MasterNode, node_mngr: NodeManagerService):
        self.node = node
        self.node_mngr = node_mngr

    @abstractmethod
    def run(self, request: tuple) -> tuple:
        pass
