"""GPS time sync mode."""

from time import monotonic

from olaf import logger

from ._mode import AdcsMode, AdcsPointAxis, Mode


class UpdateMode(Mode):
    """Update mode."""

    def __init__(self, node_id: int):
        self.card = self.node.od_db[node_id]
        super().__init__([card])

        self.state = ""

    def on_loop(self):

        if node in fw_nodes:
            self._on_loop_update_fw()
        else:
            self._on_loop_update_sw()

    def _on_loop_update_sw(self):

        logger.info(f"starting update for {self.card}")
        self.node.sdo_write(self.card, "updater", "update", True)

        sleep(1)

        update_status = self.node.od[self.card]["updater_status"].value
        if update_status == "update_successful":
            logger.info(f"update for {self.card} has completed")
            self.node.sdo_write(self.card, "updater", "make_status_file", True)
        elif update_status in ["pre_update_failed", "update_failed"]:
            logger.critical(f"update for {self.card} failed with {update_status}")

    def _on_loop_update_fw(self):

        pass  # TODO
