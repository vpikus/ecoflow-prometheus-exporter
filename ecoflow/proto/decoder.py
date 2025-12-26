"""Protobuf decoder for EcoFlow device messages.

Decodes binary protobuf messages from MQTT using the generic common and
device_common proto definitions. Works with all EcoFlow devices that send
protobuf format instead of JSON.

Only handles:
- cmd_func=254, cmd_id=21: DisplayPropertyUpload (main device status)

Other message types are logged with their original payload for debugging.
"""

import base64
import logging as log
from typing import Any

from google.protobuf.json_format import MessageToDict


def _flatten_dict(d: dict[str, Any], parent_key: str = "", sep: str = ".") -> dict[str, Any]:
    """Flatten nested dict to dot-notation keys."""
    items: list[tuple[str, Any]] = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(_flatten_dict(v, new_key, sep).items())
        elif isinstance(v, list):
            # Skip list flattening for now, just add the list as-is
            items.append((new_key, v))
        else:
            items.append((new_key, v))
    return dict(items)


class ProtobufDecoder:
    """Generic protobuf decoder for all EcoFlow devices."""

    def decode(self, raw_data: bytes) -> dict[str, Any]:
        """Decode raw bytes to dictionary.

        Handles the common EcoFlow protobuf format with Header messages.
        Only processes cmd_func=254, cmd_id=21 (DisplayPropertyUpload).
        Other message types are logged with their payload.

        Args:
            raw_data: Raw bytes from MQTT message.

        Returns:
            Dictionary with decoded parameters.
        """
        from . import common_pb2 as common
        from . import device_common_pb2 as device_common

        result: dict[str, Any] = {}

        try:
            # Try base64 decode first (some devices send base64-encoded data)
            try:
                decoded = base64.b64decode(raw_data, validate=True)
                raw_data = decoded
            except Exception:
                pass

            # Parse as Send_Header_Msg container
            header_msg = common.Send_Header_Msg()
            header_msg.ParseFromString(raw_data)

            if not header_msg.msg:
                log.debug("No messages in protobuf payload")
                return result

            for header in header_msg.msg:
                cmd_func = header.cmd_func
                cmd_id = header.cmd_id
                pdata = header.pdata
                enc_type = header.enc_type
                src = header.src
                seq = header.seq

                # XOR decode if needed (enc_type=1 and src!=32)
                if enc_type == 1 and src != 32:
                    pdata = self._xor_decode(pdata, seq)

                # Only handle DisplayPropertyUpload (cmd_func=254, cmd_id=21)
                if cmd_func == 254 and cmd_id == 21:
                    try:
                        msg = device_common.DisplayPropertyUpload()
                        msg.ParseFromString(pdata)
                        data = MessageToDict(msg, preserving_proto_field_name=True)
                        result.update(_flatten_dict(data))
                        log.debug("Decoded DisplayPropertyUpload with %d fields", len(data))
                    except Exception as e:
                        log.warning(
                            "Failed to decode DisplayPropertyUpload: %s, payload (hex): %s",
                            e,
                            pdata.hex()
                        )
                else:
                    # Log unhandled message types with their payload
                    log.debug(
                        "Unhandled protobuf message: cmd_func=%d, cmd_id=%d, payload (hex): %s",
                        cmd_func,
                        cmd_id,
                        pdata.hex()
                    )

        except Exception as e:
            log.error("Protobuf decode error: %s, raw data (hex): %s", e, raw_data.hex())

        return result

    def _xor_decode(self, pdata: bytes, seq: int) -> bytes:
        """Apply XOR decoding with sequence value."""
        return bytes((b ^ seq) & 0xFF for b in pdata)


def get_decoder() -> ProtobufDecoder:
    """Get the generic protobuf decoder instance.

    Returns:
        ProtobufDecoder instance.
    """
    return ProtobufDecoder()
