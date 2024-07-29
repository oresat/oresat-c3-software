from .abc_cmd import AbcCmd, logger, struct


class CoSdoWriteCmd(AbcCmd):
    id = 6
    req_format = None
    res_format = "I"

    def run(self, request: tuple) -> tuple:
        logger.info("")

    def _edl_req_sdo_write_pack_cb(values: tuple) -> bytes:
        req = struct.pack("<BHBI", *values[:4])
        return req + values[4]

    def _edl_req_sdo_write_unpack_cb(raw: bytes) -> tuple:
        fmt = "<BHBI"
        size = struct.calcsize(fmt)
        values = struct.unpack(fmt, raw[:size])
        return values + (raw[size:],)
