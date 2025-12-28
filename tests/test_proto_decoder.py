"""Tests for ecoflow/proto/decoder.py - Protobuf decoder."""

import base64

import pytest

from ecoflow.proto import common_pb2 as common
from ecoflow.proto import device_common_pb2 as device_common
from ecoflow.proto.decoder import ProtobufDecoder, _flatten_dict, get_decoder


class TestFlattenDict:
    """Tests for _flatten_dict() helper function."""

    def test_flat_dict_unchanged(self):
        """Test that already flat dict is unchanged."""
        data = {"key1": 1, "key2": "value", "key3": 3.14}

        result = _flatten_dict(data)

        assert result == data

    def test_nested_dict_flattened(self):
        """Test that nested dict is flattened with dot notation."""
        data = {"outer": {"inner": 42}}

        result = _flatten_dict(data)

        assert result == {"outer.inner": 42}

    def test_deeply_nested_dict(self):
        """Test that deeply nested dict is fully flattened."""
        data = {"a": {"b": {"c": {"d": 1}}}}

        result = _flatten_dict(data)

        assert result == {"a.b.c.d": 1}

    def test_multiple_nested_keys(self):
        """Test flattening dict with multiple nested keys."""
        data = {
            "level1_a": {"level2_a": 1, "level2_b": 2},
            "level1_b": {"level2_c": 3},
        }

        result = _flatten_dict(data)

        assert result == {
            "level1_a.level2_a": 1,
            "level1_a.level2_b": 2,
            "level1_b.level2_c": 3,
        }

    def test_list_values_preserved(self):
        """Test that list values are preserved as-is."""
        data = {"items": [1, 2, 3], "nested": {"list": [4, 5]}}

        result = _flatten_dict(data)

        assert result == {"items": [1, 2, 3], "nested.list": [4, 5]}

    def test_empty_dict(self):
        """Test that empty dict returns empty dict."""
        result = _flatten_dict({})

        assert result == {}

    def test_mixed_value_types(self):
        """Test flattening with mixed value types."""
        data = {
            "int": 1,
            "float": 2.5,
            "string": "test",
            "bool": True,
            "nested": {"value": 100},
        }

        result = _flatten_dict(data)

        assert result == {
            "int": 1,
            "float": 2.5,
            "string": "test",
            "bool": True,
            "nested.value": 100,
        }


class TestProtobufDecoderXorDecode:
    """Tests for XOR decoding functionality."""

    def test_xor_decode_basic(self):
        """Test basic XOR decoding."""
        decoder = ProtobufDecoder()
        # XOR each byte with seq=5
        data = bytes([0x05, 0x06, 0x07, 0x08])  # 0^5=5, 1^5=6, 2^5=7, 3^5=8
        seq = 5

        result = decoder._xor_decode(data, seq)

        assert result == bytes([0x00, 0x03, 0x02, 0x0D])

    def test_xor_decode_reversible(self):
        """Test that XOR decoding is reversible."""
        decoder = ProtobufDecoder()
        original = b"test data"
        seq = 42

        # Apply XOR encoding
        encoded = decoder._xor_decode(original, seq)
        # Apply XOR decoding (same operation)
        decoded = decoder._xor_decode(encoded, seq)

        assert decoded == original

    def test_xor_decode_with_zero_seq(self):
        """Test XOR decode with seq=0 returns original."""
        decoder = ProtobufDecoder()
        data = b"unchanged"

        result = decoder._xor_decode(data, 0)

        assert result == data

    def test_xor_decode_with_high_seq(self):
        """Test XOR decode with high seq value (wraps to byte)."""
        decoder = ProtobufDecoder()
        data = bytes([0x00, 0xFF, 0x80])
        seq = 256 + 10  # Should use 10 (seq & 0xFF)

        result = decoder._xor_decode(data, seq)

        # XOR with 10 (lower 8 bits of 266)
        expected = bytes([b ^ (seq & 0xFF) for b in data])
        assert result == expected


class TestProtobufDecoderDecode:
    """Tests for decode() method with real protobuf messages."""

    @pytest.fixture
    def decoder(self):
        """Create decoder instance."""
        return ProtobufDecoder()

    def _create_header_msg(
        self,
        cmd_func: int,
        cmd_id: int,
        pdata: bytes,
        enc_type: int = 0,
        src: int = 0,
        seq: int = 0,
    ) -> bytes:
        """Helper to create a serialized Send_Header_Msg."""
        header = common.Header()
        header.cmd_func = cmd_func
        header.cmd_id = cmd_id
        header.pdata = pdata
        header.enc_type = enc_type
        header.src = src
        header.seq = seq

        msg = common.Send_Header_Msg()
        msg.msg.append(header)

        return msg.SerializeToString()

    def test_decode_display_property_upload(self, decoder):
        """Test decoding a valid DisplayPropertyUpload message."""
        # Create DisplayPropertyUpload with some fields
        # Note: protobuf3 doesn't serialize default values (0, empty string, etc.)
        display_msg = device_common.DisplayPropertyUpload()
        display_msg.errcode = 1001  # Non-zero to ensure serialization
        display_msg.sys_status = 1
        display_msg.pow_in_sum_w = 100.5
        display_msg.pow_out_sum_w = 50.25
        display_msg.bms_batt_soc = 85
        display_msg.cms_batt_soc = 90

        # Wrap in header with cmd_func=254, cmd_id=21
        raw_data = self._create_header_msg(
            cmd_func=254,
            cmd_id=21,
            pdata=display_msg.SerializeToString(),
        )

        result = decoder.decode(raw_data)

        assert result["errcode"] == 1001
        assert result["sys_status"] == 1
        assert abs(result["pow_in_sum_w"] - 100.5) < 0.01
        assert abs(result["pow_out_sum_w"] - 50.25) < 0.01
        assert result["bms_batt_soc"] == 85
        assert result["cms_batt_soc"] == 90

    def test_decode_with_usb_display_info(self, decoder):
        """Test decoding with nested UsbRealDisplayInfo message."""
        display_msg = device_common.DisplayPropertyUpload()

        # Set USB TypeC1 display info
        display_msg.usb_typec1_display_info.usb_pow = -45.5  # Output power
        display_msg.usb_typec1_display_info.usb_vol = 20.0
        display_msg.usb_typec1_display_info.usb_amp = 2.275

        raw_data = self._create_header_msg(
            cmd_func=254,
            cmd_id=21,
            pdata=display_msg.SerializeToString(),
        )

        result = decoder.decode(raw_data)

        # Nested messages should be flattened
        assert "usb_typec1_display_info.usb_pow" in result
        assert abs(result["usb_typec1_display_info.usb_pow"] - (-45.5)) < 0.01
        assert abs(result["usb_typec1_display_info.usb_vol"] - 20.0) < 0.01
        assert abs(result["usb_typec1_display_info.usb_amp"] - 2.275) < 0.01

    def test_decode_base64_encoded(self, decoder):
        """Test decoding base64-encoded message."""
        display_msg = device_common.DisplayPropertyUpload()
        display_msg.bms_batt_soc = 75
        display_msg.pow_in_sum_w = 120.0

        raw_msg = self._create_header_msg(
            cmd_func=254,
            cmd_id=21,
            pdata=display_msg.SerializeToString(),
        )

        # Base64 encode the message
        base64_data = base64.b64encode(raw_msg)

        result = decoder.decode(base64_data)

        assert result["bms_batt_soc"] == 75
        assert abs(result["pow_in_sum_w"] - 120.0) < 0.01

    def test_decode_xor_encoded(self, decoder):
        """Test decoding XOR-encoded message (enc_type=1, src!=32)."""
        display_msg = device_common.DisplayPropertyUpload()
        display_msg.bms_batt_soc = 80

        pdata = display_msg.SerializeToString()
        seq = 42

        # XOR encode the pdata
        encoded_pdata = bytes((b ^ seq) & 0xFF for b in pdata)

        raw_data = self._create_header_msg(
            cmd_func=254,
            cmd_id=21,
            pdata=encoded_pdata,
            enc_type=1,
            src=0,  # Not 32, so XOR decode will be applied
            seq=seq,
        )

        result = decoder.decode(raw_data)

        assert result["bms_batt_soc"] == 80

    def test_decode_xor_skipped_when_src_32(self, decoder):
        """Test that XOR is skipped when src=32."""
        display_msg = device_common.DisplayPropertyUpload()
        display_msg.bms_batt_soc = 65

        raw_data = self._create_header_msg(
            cmd_func=254,
            cmd_id=21,
            pdata=display_msg.SerializeToString(),
            enc_type=1,
            src=32,  # src=32 means no XOR decode
            seq=100,
        )

        result = decoder.decode(raw_data)

        assert result["bms_batt_soc"] == 65

    def test_decode_empty_message(self, decoder):
        """Test decoding empty Send_Header_Msg."""
        msg = common.Send_Header_Msg()  # No headers
        raw_data = msg.SerializeToString()

        result = decoder.decode(raw_data)

        assert result == {}

    def test_decode_unhandled_cmd_func(self, decoder):
        """Test that unhandled cmd_func is skipped."""
        display_msg = device_common.DisplayPropertyUpload()
        display_msg.bms_batt_soc = 99

        raw_data = self._create_header_msg(
            cmd_func=100,  # Not 254
            cmd_id=21,
            pdata=display_msg.SerializeToString(),
        )

        result = decoder.decode(raw_data)

        assert result == {}

    def test_decode_unhandled_cmd_id(self, decoder):
        """Test that unhandled cmd_id is skipped."""
        display_msg = device_common.DisplayPropertyUpload()
        display_msg.bms_batt_soc = 99

        raw_data = self._create_header_msg(
            cmd_func=254,
            cmd_id=100,  # Not 21
            pdata=display_msg.SerializeToString(),
        )

        result = decoder.decode(raw_data)

        assert result == {}

    def test_decode_invalid_protobuf(self, decoder):
        """Test handling of invalid protobuf data."""
        invalid_data = b"\xff\xfe\xfd\xfc\xfb\xfa"

        result = decoder.decode(invalid_data)

        assert result == {}

    def test_decode_corrupt_pdata(self, decoder):
        """Test handling of corrupt pdata in valid header."""
        raw_data = self._create_header_msg(
            cmd_func=254,
            cmd_id=21,
            pdata=b"\xff\xff\xff\xff",  # Invalid DisplayPropertyUpload
        )

        result = decoder.decode(raw_data)

        # Should return empty dict, not raise
        assert result == {}

    def test_decode_multiple_headers(self, decoder):
        """Test decoding message with multiple headers."""
        msg1 = device_common.DisplayPropertyUpload()
        msg1.bms_batt_soc = 50

        msg2 = device_common.DisplayPropertyUpload()
        msg2.bms_batt_soc = 60
        msg2.pow_in_sum_w = 200.0

        header1 = common.Header()
        header1.cmd_func = 254
        header1.cmd_id = 21
        header1.pdata = msg1.SerializeToString()

        header2 = common.Header()
        header2.cmd_func = 254
        header2.cmd_id = 21
        header2.pdata = msg2.SerializeToString()

        container = common.Send_Header_Msg()
        container.msg.append(header1)
        container.msg.append(header2)

        raw_data = container.SerializeToString()

        result = decoder.decode(raw_data)

        # Second message should override first
        assert result["bms_batt_soc"] == 60
        assert abs(result["pow_in_sum_w"] - 200.0) < 0.01

    def test_decode_mixed_valid_invalid_headers(self, decoder):
        """Test decoding with mix of valid and invalid headers."""
        valid_msg = device_common.DisplayPropertyUpload()
        valid_msg.cms_batt_soc = 77

        header1 = common.Header()
        header1.cmd_func = 100  # Invalid cmd_func
        header1.cmd_id = 21
        header1.pdata = b"ignored"

        header2 = common.Header()
        header2.cmd_func = 254
        header2.cmd_id = 21
        header2.pdata = valid_msg.SerializeToString()

        container = common.Send_Header_Msg()
        container.msg.append(header1)
        container.msg.append(header2)

        raw_data = container.SerializeToString()

        result = decoder.decode(raw_data)

        assert result["cms_batt_soc"] == 77


class TestProtobufDecoderRealWorldScenarios:
    """Tests simulating real-world device messages."""

    @pytest.fixture
    def decoder(self):
        """Create decoder instance."""
        return ProtobufDecoder()

    def test_decode_rapid_pro_charger_status(self, decoder):
        """Test decoding RAPID Pro Desktop Charger status message."""
        display_msg = device_common.DisplayPropertyUpload()

        # Typical charger status (use non-zero values for proto3 serialization)
        display_msg.sys_status = 2
        display_msg.pow_out_sum_w = 45.5
        display_msg.lcd_light = 100
        display_msg.dev_standby_time = 300

        # USB outputs
        display_msg.pow_get_typec1 = -45.5

        # Battery status (if connected)
        display_msg.bms_batt_soc = 85
        display_msg.cms_batt_soc = 85

        # WiFi signal
        display_msg.module_wifi_rssi = -55

        header = common.Header()
        header.cmd_func = 254
        header.cmd_id = 21
        header.pdata = display_msg.SerializeToString()
        header.product_id = 23809  # RAPID Pro product ID

        container = common.Send_Header_Msg()
        container.msg.append(header)

        raw_data = container.SerializeToString()

        result = decoder.decode(raw_data)

        assert result["sys_status"] == 2
        assert abs(result["pow_out_sum_w"] - 45.5) < 0.01
        assert result["lcd_light"] == 100
        assert result["bms_batt_soc"] == 85
        assert result["module_wifi_rssi"] == -55

    def test_decode_delta_pro_status(self, decoder):
        """Test decoding DELTA Pro power station status."""
        display_msg = device_common.DisplayPropertyUpload()

        # Power station typical status
        display_msg.errcode = 0
        display_msg.sys_status = 1
        display_msg.pow_in_sum_w = 400.0  # Solar charging
        display_msg.pow_out_sum_w = 150.0  # Load output

        # Battery status
        display_msg.bms_batt_soc = 72
        display_msg.cms_batt_soc = 72
        display_msg.bms_dsg_rem_time = 180  # 3 hours remaining
        display_msg.bms_chg_rem_time = 120  # 2 hours to full

        # Temperature
        display_msg.bms_min_cell_temp = 25
        display_msg.bms_max_cell_temp = 28

        # AC output
        display_msg.ac_out_open = True
        display_msg.pow_get_ac_out = -150.0

        header = common.Header()
        header.cmd_func = 254
        header.cmd_id = 21
        header.pdata = display_msg.SerializeToString()

        container = common.Send_Header_Msg()
        container.msg.append(header)

        raw_data = container.SerializeToString()

        result = decoder.decode(raw_data)

        assert result["bms_batt_soc"] == 72
        assert result["bms_dsg_rem_time"] == 180
        assert result["bms_min_cell_temp"] == 25
        assert result["ac_out_open"] is True

    def test_decode_with_error_code(self, decoder):
        """Test decoding message with error codes."""
        display_msg = device_common.DisplayPropertyUpload()

        # Use non-zero error codes (proto3 doesn't serialize 0 values)
        display_msg.errcode = 1001  # Some error
        display_msg.pd_err_code = 2001
        display_msg.bms_err_code = 3001  # Non-zero
        display_msg.sys_status = 3  # Error state

        header = common.Header()
        header.cmd_func = 254
        header.cmd_id = 21
        header.pdata = display_msg.SerializeToString()

        container = common.Send_Header_Msg()
        container.msg.append(header)

        raw_data = container.SerializeToString()

        result = decoder.decode(raw_data)

        assert result["errcode"] == 1001
        assert result["pd_err_code"] == 2001
        assert result["bms_err_code"] == 3001
        assert result["sys_status"] == 3


class TestGetDecoder:
    """Tests for get_decoder() factory function."""

    def test_get_decoder_returns_instance(self):
        """Test that get_decoder returns a ProtobufDecoder."""
        decoder = get_decoder()

        assert isinstance(decoder, ProtobufDecoder)

    def test_get_decoder_returns_new_instances(self):
        """Test that get_decoder returns new instances each call."""
        decoder1 = get_decoder()
        decoder2 = get_decoder()

        # They should be different instances
        assert decoder1 is not decoder2

    def test_decoder_from_factory_works(self):
        """Test that decoder from factory can decode messages."""
        decoder = get_decoder()

        display_msg = device_common.DisplayPropertyUpload()
        display_msg.bms_batt_soc = 42

        header = common.Header()
        header.cmd_func = 254
        header.cmd_id = 21
        header.pdata = display_msg.SerializeToString()

        container = common.Send_Header_Msg()
        container.msg.append(header)

        raw_data = container.SerializeToString()

        result = decoder.decode(raw_data)

        assert result["bms_batt_soc"] == 42


class TestProtobufDecoderEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.fixture
    def decoder(self):
        """Create decoder instance."""
        return ProtobufDecoder()

    def test_decode_empty_bytes(self, decoder):
        """Test decoding empty bytes."""
        result = decoder.decode(b"")

        assert result == {}

    def test_decode_single_byte(self, decoder):
        """Test decoding single byte (invalid protobuf)."""
        result = decoder.decode(b"\x00")

        assert result == {}

    def test_decode_large_message(self, decoder):
        """Test decoding large message with many fields."""
        display_msg = device_common.DisplayPropertyUpload()

        # Set many fields
        display_msg.errcode = 0
        display_msg.sys_status = 1
        display_msg.pow_in_sum_w = 500.0
        display_msg.pow_out_sum_w = 300.0
        display_msg.bms_batt_soc = 95
        display_msg.cms_batt_soc = 95
        display_msg.bms_dsg_rem_time = 600
        display_msg.bms_chg_rem_time = 30
        display_msg.bms_min_cell_temp = 20
        display_msg.bms_max_cell_temp = 25
        display_msg.ac_out_open = True
        display_msg.dc_out_open = True
        display_msg.xboost_en = True
        display_msg.module_wifi_rssi = -45
        display_msg.lcd_light = 80
        display_msg.dev_standby_time = 600
        display_msg.en_beep = True

        header = common.Header()
        header.cmd_func = 254
        header.cmd_id = 21
        header.pdata = display_msg.SerializeToString()

        container = common.Send_Header_Msg()
        container.msg.append(header)

        raw_data = container.SerializeToString()

        result = decoder.decode(raw_data)

        # Verify several fields
        assert result["bms_batt_soc"] == 95
        assert result["ac_out_open"] is True
        assert result["en_beep"] is True
        assert result["module_wifi_rssi"] == -45

    def test_decode_with_zero_values(self, decoder):
        """Test decoding message with zero values."""
        display_msg = device_common.DisplayPropertyUpload()
        display_msg.errcode = 0
        display_msg.bms_batt_soc = 0
        display_msg.pow_in_sum_w = 0.0

        header = common.Header()
        header.cmd_func = 254
        header.cmd_id = 21
        header.pdata = display_msg.SerializeToString()

        container = common.Send_Header_Msg()
        container.msg.append(header)

        raw_data = container.SerializeToString()

        result = decoder.decode(raw_data)

        # Zero values should still be present
        assert result.get("errcode", 0) == 0
        assert result.get("bms_batt_soc", 0) == 0

    def test_decode_with_negative_temperatures(self, decoder):
        """Test decoding message with negative temperature values."""
        display_msg = device_common.DisplayPropertyUpload()
        display_msg.bms_min_cell_temp = -10
        display_msg.bms_max_cell_temp = -5
        display_msg.temp_ambient = -20

        header = common.Header()
        header.cmd_func = 254
        header.cmd_id = 21
        header.pdata = display_msg.SerializeToString()

        container = common.Send_Header_Msg()
        container.msg.append(header)

        raw_data = container.SerializeToString()

        result = decoder.decode(raw_data)

        assert result["bms_min_cell_temp"] == -10
        assert result["bms_max_cell_temp"] == -5
        assert result["temp_ambient"] == -20

    def test_decode_with_string_fields(self, decoder):
        """Test decoding message with string fields."""
        display_msg = device_common.DisplayPropertyUpload()
        display_msg.bms_main_sn = "BMS123456789"
        display_msg.module_wifi_ssid = "MyWiFiNetwork"

        header = common.Header()
        header.cmd_func = 254
        header.cmd_id = 21
        header.pdata = display_msg.SerializeToString()

        container = common.Send_Header_Msg()
        container.msg.append(header)

        raw_data = container.SerializeToString()

        result = decoder.decode(raw_data)

        assert result["bms_main_sn"] == "BMS123456789"
        assert result["module_wifi_ssid"] == "MyWiFiNetwork"

    def test_decode_invalid_base64_falls_back_to_raw(self, decoder):
        """Test that invalid base64 falls back to raw parsing."""
        display_msg = device_common.DisplayPropertyUpload()
        display_msg.bms_batt_soc = 55

        header = common.Header()
        header.cmd_func = 254
        header.cmd_id = 21
        header.pdata = display_msg.SerializeToString()

        container = common.Send_Header_Msg()
        container.msg.append(header)

        raw_data = container.SerializeToString()

        # This is not valid base64, but it's valid protobuf
        result = decoder.decode(raw_data)

        assert result["bms_batt_soc"] == 55
