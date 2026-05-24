"""
Node Flasher Service
Handles flashing Zephyr/MCUboot images to nodes via CANopen.
"""

import os
import time
from queue import Empty, SimpleQueue

import canopen
from olaf import Service, logger

H1F50_PROGRAM_DATA = 0x1F50
H1F51_PROGRAM_CTRL = 0x1F51
H1F56_PROGRAM_SWID = 0x1F56
H1F57_FLASH_STATUS = 0x1F57

PROGRAM_CTRL_STOP = 0x00
PROGRAM_CTRL_START = 0x01
PROGRAM_CTRL_CLEAR = 0x03


class NodeFlasherService(Service):
    def __init__(self, cache_dir: str, node_mgr):
        super().__init__()
        self.cache_dir = cache_dir
        self.node_mgr = node_mgr
        self.command_queue = SimpleQueue()

        self.status_timeout = 30.0
        self.bootup_timeout = 20.0
        self.download_buffer_size = 889
        self.block_transfer = False

    def enqueue_flash(self, node_id: int, filename: str):
        """Called by EdlService to trigger a flash."""
        self.command_queue.put({"node_id": node_id, "filename": filename})
        logger.info(f"Queued flash for Node 0x{node_id:02X} with file {filename}")

    def on_loop(self):
        """TODO: Comment?."""
        try:
            cmd = self.command_queue.get(timeout=1.0)
            self._execute_flash(cmd["node_id"], cmd["filename"])
        except Empty:
            pass
        except Exception as e:
            logger.error(f"Node flasher error: {e}")

    def _wait_flash_status_ok(self, flash_sdo, timeout_s):
        end = time.time() + timeout_s
        status = int(flash_sdo.raw)
        while status != 0 and time.time() < end:
            time.sleep(0.5)
            status = int(flash_sdo.raw)
        return status

    def _execute_flash(self, node_id: int, filename: str):
        filepath = os.path.join(self.cache_dir, filename)

        if not os.path.isfile(filepath):
            logger.error(f"Node flasher aborted: File not found at {filepath}")
            return

        node_name = self.node_mgr.node_id_to_name.get(node_id)
        if node_name is None:
            logger.error(
                f"Node flasher aborted: Node 0x{node_id:02X} not in node_id_to_name. "
            )
            return

        if node_name not in self.node.remote_nodes:
            logger.error(
                f"Node flasher aborted: Node {node_name} (0x{node_id:02X}) not in remote_nodes. "
            )
            return

        target_node = self.node.remote_nodes[node_name]

        data_sdo = target_node.sdo[H1F50_PROGRAM_DATA][1]
        ctrl_sdo = target_node.sdo[H1F51_PROGRAM_CTRL][1]
        flash_sdo = target_node.sdo[H1F57_FLASH_STATUS][1]

        logger.info(f"Starting flash of {filename} to Node {node_name} (0x{node_id:02X})")
        try:
            self.node_mgr.set_node_updating(node_id, True)

            target_node.nmt.state = "PRE-OPERATIONAL"
            time.sleep(0.5)

            # Clear old image
            ctrl_sdo.raw = PROGRAM_CTRL_STOP
            ctrl_sdo.raw = PROGRAM_CTRL_CLEAR
            if self._wait_flash_status_ok(flash_sdo, self.status_timeout) != 0:
                raise Exception("CLEAR command failed or timed out.")

            # Download new image
            file_size = os.path.getsize(filepath)
            logger.info(f"Downloading {file_size} bytes...")
            with open(filepath, "rb") as infile:
                outfile = data_sdo.open(
                    "wb",
                    buffering=self.download_buffer_size,
                    size=file_size,
                    block_transfer=self.block_transfer,
                )
                outfile.write(infile.read())
                outfile.close()

            if self._wait_flash_status_ok(flash_sdo, self.status_timeout) != 0:
                raise Exception("DOWNLOAD failed or timed out.")

            # Reboot node
            logger.info("Download complete. Rebooting node...")
            ctrl_sdo.raw = PROGRAM_CTRL_START
            target_node.nmt.wait_for_bootup(timeout=self.bootup_timeout)
            logger.info(f"Node {node_name} (0x{node_id:02X}) flashed and rebooted successfully.")

        except Exception as e:
            logger.error(f"Node flasher failed during execution: {e}")
        finally:
            self.node_mgr.set_node_updating(node_id, False)

            try:
                os.remove(filepath)
                logger.info(f"Cleaned up {filename} from cache.")
            except OSError as e:
                logger.warning(f"Could not delete {filename}: {e}")
