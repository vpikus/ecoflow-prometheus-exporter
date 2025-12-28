"""Tests for ecoflow/devices.py - Device discovery and resolution."""

# We need to reset the module cache before importing
import importlib
import json
import os
import tempfile


def reload_devices_module():
    """Reload the devices module to reset cache and re-read env vars."""
    import ecoflow.devices

    # Actually reload the module to pick up new env vars for DEVICES_JSON_PATH
    importlib.reload(ecoflow.devices)
    return ecoflow.devices


class TestLoadDevices:
    """Tests for _load_devices() function."""

    def test_load_valid_devices_file(self, temp_devices_file, clean_env):
        """Test loading a valid devices.json file."""
        os.environ["ECOFLOW_DEVICES_JSON"] = temp_devices_file
        devices = reload_devices_module()

        result = devices._load_devices()

        assert len(result) == 4
        assert result[0]["generalKey"] == "ecoflow_rapid_pro_charging_dock"
        assert result[0]["sn"] == "P521"

    def test_load_empty_devices_file(self, empty_devices_file, clean_env):
        """Test loading an empty devices.json file."""
        os.environ["ECOFLOW_DEVICES_JSON"] = empty_devices_file
        devices = reload_devices_module()

        result = devices._load_devices()

        assert result == []

    def test_load_nonexistent_file(self, clean_env):
        """Test loading a non-existent file returns empty list."""
        os.environ["ECOFLOW_DEVICES_JSON"] = "/nonexistent/path/devices.json"
        devices = reload_devices_module()

        result = devices._load_devices()

        assert result == []

    def test_load_invalid_json(self, invalid_json_file, clean_env):
        """Test loading invalid JSON returns empty list."""
        os.environ["ECOFLOW_DEVICES_JSON"] = invalid_json_file
        devices = reload_devices_module()

        result = devices._load_devices()

        assert result == []

    def test_caching_behavior(self, temp_devices_file, clean_env):
        """Test that devices are cached after first load."""
        os.environ["ECOFLOW_DEVICES_JSON"] = temp_devices_file
        devices = reload_devices_module()

        # First load
        result1 = devices._load_devices()
        assert len(result1) == 4

        # Modify the file
        with open(temp_devices_file, "w") as f:
            json.dump([{"sn": "NEW", "name": "New Device"}], f)

        # Second load should return cached data
        result2 = devices._load_devices()
        assert len(result2) == 4  # Still 4, not 1
        assert result1 is result2  # Same object


class TestFindMatchingDevice:
    """Tests for _find_matching_device() function."""

    def test_find_exact_prefix_match(self, temp_devices_file, clean_env):
        """Test finding device with exact prefix match."""
        os.environ["ECOFLOW_DEVICES_JSON"] = temp_devices_file
        devices = reload_devices_module()

        result = devices._find_matching_device("P521ZE1B3H6J0717")

        assert result is not None
        assert result["sn"] == "P521"
        assert result["generalKey"] == "ecoflow_rapid_pro_charging_dock"

    def test_find_short_prefix_match(self, temp_devices_file, clean_env):
        """Test finding device with short prefix match."""
        os.environ["ECOFLOW_DEVICES_JSON"] = temp_devices_file
        devices = reload_devices_module()

        result = devices._find_matching_device("DCA12345678")

        assert result is not None
        assert result["sn"] == "DCA"
        assert result["generalKey"] == "ecoflow_ps_delta_pro_3600"

    def test_no_matching_device(self, temp_devices_file, clean_env):
        """Test when no device matches the SN prefix."""
        os.environ["ECOFLOW_DEVICES_JSON"] = temp_devices_file
        devices = reload_devices_module()

        result = devices._find_matching_device("UNKNOWN123456")

        assert result is None

    def test_empty_devices_list(self, empty_devices_file, clean_env):
        """Test finding device in empty devices list."""
        os.environ["ECOFLOW_DEVICES_JSON"] = empty_devices_file
        devices = reload_devices_module()

        result = devices._find_matching_device("P521ZE1B3H6J0717")

        assert result is None

    def test_first_match_wins(self, clean_env):
        """Test that first matching prefix is returned."""
        # Create file with overlapping prefixes
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(
                [
                    {"sn": "P5", "name": "Short Prefix", "generalKey": "short"},
                    {"sn": "P521", "name": "Long Prefix", "generalKey": "long"},
                ],
                f,
            )
            temp_path = f.name

        try:
            os.environ["ECOFLOW_DEVICES_JSON"] = temp_path
            devices = reload_devices_module()

            result = devices._find_matching_device("P521ZE1B3H6J0717")

            # First match (P5) should win
            assert result["generalKey"] == "short"
        finally:
            os.unlink(temp_path)


class TestGetProductName:
    """Tests for get_product_name() function."""

    def test_get_product_name_matching_device(self, temp_devices_file, clean_env):
        """Test getting product name for matching device."""
        os.environ["ECOFLOW_DEVICES_JSON"] = temp_devices_file
        devices = reload_devices_module()

        result = devices.get_product_name("P521ZE1B3H6J0717")

        assert result == "RAPID Pro Desktop Charger"

    def test_get_product_name_no_match(self, temp_devices_file, clean_env):
        """Test getting product name for non-matching device."""
        os.environ["ECOFLOW_DEVICES_JSON"] = temp_devices_file
        devices = reload_devices_module()

        result = devices.get_product_name("UNKNOWN123456")

        assert result is None

    def test_get_product_name_device_without_name(self, clean_env):
        """Test getting product name when device entry has no name."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump([{"sn": "TEST", "generalKey": "test_key"}], f)
            temp_path = f.name

        try:
            os.environ["ECOFLOW_DEVICES_JSON"] = temp_path
            devices = reload_devices_module()

            result = devices.get_product_name("TEST123456")

            assert result is None
        finally:
            os.unlink(temp_path)


class TestGetDeviceGeneralKey:
    """Tests for get_device_general_key() function."""

    def test_env_var_override(self, temp_devices_file, clean_env):
        """Test that environment variable takes priority."""
        os.environ["ECOFLOW_DEVICES_JSON"] = temp_devices_file
        os.environ["ECOFLOW_DEVICE_GENERAL_KEY"] = "custom_key_from_env"

        # Need to reload to pick up new env var
        import ecoflow.devices

        importlib.reload(ecoflow.devices)
        ecoflow.devices._devices_cache = None

        result = ecoflow.devices.get_device_general_key("P521ZE1B3H6J0717")

        assert result == "custom_key_from_env"

    def test_matching_device_from_file(self, temp_devices_file, clean_env):
        """Test getting general key from matching device in file."""
        os.environ["ECOFLOW_DEVICES_JSON"] = temp_devices_file
        devices = reload_devices_module()

        result = devices.get_device_general_key("R601ABCD1234")

        assert result == "ecoflow_ps_river_256"

    def test_no_match_returns_unknown(self, temp_devices_file, clean_env):
        """Test that unknown is returned when no match found."""
        os.environ["ECOFLOW_DEVICES_JSON"] = temp_devices_file
        devices = reload_devices_module()

        result = devices.get_device_general_key("UNKNOWN123456")

        assert result == "unknown"

    def test_device_without_general_key(self, clean_env):
        """Test device entry without generalKey field."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump([{"sn": "TEST", "name": "Test Device"}], f)
            temp_path = f.name

        try:
            os.environ["ECOFLOW_DEVICES_JSON"] = temp_path
            devices = reload_devices_module()

            result = devices.get_device_general_key("TEST123456")

            assert result == "unknown"
        finally:
            os.unlink(temp_path)


class TestBuildDeviceName:
    """Tests for build_device_name() function."""

    def test_env_var_override(self, temp_devices_file, clean_env):
        """Test that environment variable takes priority."""
        os.environ["ECOFLOW_DEVICES_JSON"] = temp_devices_file
        os.environ["ECOFLOW_DEVICE_NAME"] = "Custom Device Name"
        devices = reload_devices_module()

        result = devices.build_device_name("P521ZE1B3H6J0717", "P521ZE1B3H6J0717")

        assert result == "Custom Device Name"

    def test_api_name_different_from_sn(self, temp_devices_file, clean_env):
        """Test that API name is used when different from SN."""
        os.environ["ECOFLOW_DEVICES_JSON"] = temp_devices_file
        devices = reload_devices_module()

        result = devices.build_device_name("P521ZE1B3H6J0717", "My Custom Name")

        assert result == "My Custom Name"

    def test_api_name_equals_sn_with_match(self, temp_devices_file, clean_env):
        """Test building friendly name when API name equals SN and device matches."""
        os.environ["ECOFLOW_DEVICES_JSON"] = temp_devices_file
        devices = reload_devices_module()

        result = devices.build_device_name("P521ZE1B3H6J0717", "P521ZE1B3H6J0717")

        assert result == "RAPID Pro Desktop Charger-0717"

    def test_api_name_equals_sn_no_match(self, temp_devices_file, clean_env):
        """Test fallback to SN when API name equals SN and no device match."""
        os.environ["ECOFLOW_DEVICES_JSON"] = temp_devices_file
        devices = reload_devices_module()

        result = devices.build_device_name("UNKNOWN123456", "UNKNOWN123456")

        assert result == "UNKNOWN123456"

    def test_api_name_none_with_match(self, temp_devices_file, clean_env):
        """Test building friendly name when API name is None."""
        os.environ["ECOFLOW_DEVICES_JSON"] = temp_devices_file
        devices = reload_devices_module()

        result = devices.build_device_name("DCA12345678", None)

        assert result == "DELTA Pro-5678"

    def test_api_name_none_no_match(self, temp_devices_file, clean_env):
        """Test fallback to SN when API name is None and no match."""
        os.environ["ECOFLOW_DEVICES_JSON"] = temp_devices_file
        devices = reload_devices_module()

        result = devices.build_device_name("UNKNOWN123456", None)

        assert result == "UNKNOWN123456"

    def test_short_sn(self, temp_devices_file, clean_env):
        """Test handling of short serial numbers (less than 4 chars)."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump([{"sn": "X", "name": "Short SN Device"}], f)
            temp_path = f.name

        try:
            os.environ["ECOFLOW_DEVICES_JSON"] = temp_path
            devices = reload_devices_module()

            result = devices.build_device_name("XY", "XY")

            assert result == "Short SN Device-XY"
        finally:
            os.unlink(temp_path)

    def test_empty_api_name(self, temp_devices_file, clean_env):
        """Test that empty string API name triggers fallback."""
        os.environ["ECOFLOW_DEVICES_JSON"] = temp_devices_file
        devices = reload_devices_module()

        result = devices.build_device_name("P521ZE1B3H6J0717", "")

        # Empty string is falsy, should build friendly name
        assert result == "RAPID Pro Desktop Charger-0717"

    def test_device_without_name_field(self, clean_env):
        """Test device entry without name field falls back to SN."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump([{"sn": "TEST", "generalKey": "test_key"}], f)
            temp_path = f.name

        try:
            os.environ["ECOFLOW_DEVICES_JSON"] = temp_path
            devices = reload_devices_module()

            result = devices.build_device_name("TEST123456", "TEST123456")

            assert result == "TEST123456"
        finally:
            os.unlink(temp_path)
