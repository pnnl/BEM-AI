import os
import shutil
import tempfile
from unittest.mock import patch, Mock

import pytest

from os_model_util import load_os_model


class TestLoadOSModel:
    """Test class for load_os_model function"""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for test files"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def valid_osm_file(self, temp_dir):
        """Create a valid .osm file with some content"""
        file_path = os.path.join(temp_dir, "test_model.osm")
        with open(file_path, "w") as f:
            f.write("OS:Version,3.4.0;\n")  # Basic OSM content
        return file_path

    @pytest.fixture
    def empty_osm_file(self, temp_dir):
        """Create an empty .osm file"""
        file_path = os.path.join(temp_dir, "empty_model.osm")
        with open(file_path, "w") as f:
            pass  # Create empty file
        return file_path

    @pytest.fixture
    def invalid_extension_file(self, temp_dir):
        """Create a file with invalid extension"""
        file_path = os.path.join(temp_dir, "model.txt")
        with open(file_path, "w") as f:
            f.write("Some content")
        return file_path

    @pytest.fixture
    def directory_path(self, temp_dir):
        """Create a directory path"""
        dir_path = os.path.join(temp_dir, "test_directory")
        os.makedirs(dir_path)
        return dir_path

    # Test input validation
    def test_non_string_input(self):
        """Test that non-string inputs raise ValueError"""
        with pytest.raises(ValueError, match="model_path must be a string"):
            load_os_model(None)

        with pytest.raises(ValueError, match="model_path must be a string"):
            load_os_model(123)

        with pytest.raises(ValueError, match="model_path must be a string"):
            load_os_model([])

    def test_empty_string_input(self):
        """Test that empty strings raise ValueError"""
        with pytest.raises(
            ValueError, match="model_path cannot be empty or whitespace"
        ):
            load_os_model("")

        with pytest.raises(
            ValueError, match="model_path cannot be empty or whitespace"
        ):
            load_os_model("   ")

        with pytest.raises(
            ValueError, match="model_path cannot be empty or whitespace"
        ):
            load_os_model("\t\n")

    # Test file existence checks
    def test_nonexistent_file(self):
        """Test that nonexistent files raise FileNotFoundError"""
        nonexistent_path = "/path/that/does/not/exist.osm"
        with pytest.raises(FileNotFoundError, match="File does not exist"):
            load_os_model(nonexistent_path)

    def test_directory_instead_of_file(self, directory_path):
        """Test that directories raise FileNotFoundError"""
        with pytest.raises(FileNotFoundError, match="Path is not a file"):
            load_os_model(directory_path)

    def test_invalid_file_extension(self, invalid_extension_file):
        """Test that files with wrong extension raise FileNotFoundError"""
        with pytest.raises(FileNotFoundError, match="File must have .osm extension"):
            load_os_model(invalid_extension_file)

    def test_case_insensitive_extension(self, temp_dir):
        """Test that .OSM (uppercase) extension is accepted"""
        file_path = os.path.join(temp_dir, "test_model.OSM")
        with open(file_path, "w") as f:
            f.write("OS:Version,3.4.0;\n")

        # Should not raise an exception for case validation
        # We'll mock the OpenStudio parts to focus on extension validation
        with patch(
            "openstudio.openstudioosversion.VersionTranslator"
        ) as mock_translator:
            mock_optional = Mock()
            mock_optional.is_initialized.return_value = True
            mock_model = Mock()
            mock_optional.get.return_value = mock_model

            mock_cloned = Mock()
            mock_cloned.is_initialized.return_value = True
            mock_final_model = Mock()
            mock_cloned.to_Model.return_value = mock_final_model
            mock_model.clone.return_value = mock_cloned

            mock_translator_instance = Mock()
            mock_translator_instance.loadModel.return_value = mock_optional
            mock_translator.return_value = mock_translator_instance

            result = load_os_model(file_path)
            assert result == mock_final_model

    def test_empty_file(self, empty_osm_file):
        """Test that empty files raise FileNotFoundError"""
        with pytest.raises(FileNotFoundError, match="File is empty"):
            load_os_model(empty_osm_file)

    @patch("os.access")
    def test_unreadable_file(self, mock_access, valid_osm_file):
        """Test that unreadable files raise FileNotFoundError"""
        mock_access.return_value = False
        with pytest.raises(FileNotFoundError, match="File is not readable"):
            load_os_model(valid_osm_file)

    @patch("os.path.getsize")
    def test_file_size_access_error(self, mock_getsize, valid_osm_file):
        """Test that OSError when accessing file size is handled"""
        mock_getsize.side_effect = OSError("Permission denied")
        with pytest.raises(FileNotFoundError, match="Cannot access file size"):
            load_os_model(valid_osm_file)

    # Test path normalization
    def test_relative_path(self, temp_dir):
        """Test that relative paths are handled correctly"""
        # Create file in temp dir
        file_path = os.path.join(temp_dir, "test_model.osm")
        with open(file_path, "w") as f:
            f.write("OS:Version,3.4.0;\n")

        # Change to temp dir and use relative path
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            with patch(
                "openstudio.openstudioosversion.VersionTranslator"
            ) as mock_translator:
                self._setup_successful_mock(mock_translator)
                result = load_os_model("./test_model.osm")
                assert result is not None
        finally:
            os.chdir(original_cwd)

    def test_path_with_whitespace(self, temp_dir):
        """Test that paths with leading/trailing whitespace are handled"""
        file_path = os.path.join(temp_dir, "test_model.osm")
        with open(file_path, "w") as f:
            f.write("OS:Version,3.4.0;\n")

        with patch(
            "openstudio.openstudioosversion.VersionTranslator"
        ) as mock_translator:
            self._setup_successful_mock(mock_translator)
            result = load_os_model(f"  {file_path}  ")
            assert result is not None

    # Test OpenStudio integration
    @patch("openstudio.openstudioosversion.VersionTranslator")
    def test_successful_model_loading(self, mock_translator, valid_osm_file):
        """Test successful model loading and cloning"""
        self._setup_successful_mock(mock_translator)

        result = load_os_model(valid_osm_file)

        # Verify the result is the expected mock object
        assert result is not None
        mock_translator.assert_called_once()

    @patch("openstudio.openstudioosversion.VersionTranslator")
    def test_model_loading_failure(self, mock_translator, valid_osm_file):
        """Test OpenStudio model loading failure"""
        mock_optional = Mock()
        mock_optional.is_initialized.return_value = False

        mock_translator_instance = Mock()
        mock_translator_instance.loadModel.return_value = mock_optional
        mock_translator.return_value = mock_translator_instance

        with pytest.raises(RuntimeError, match="Failed to load OpenStudio model"):
            load_os_model(valid_osm_file)

    @patch("openstudio.openstudioosversion.VersionTranslator")
    def test_model_cloning_failure(self, mock_translator, valid_osm_file):
        """Test OpenStudio model cloning failure"""
        mock_optional = Mock()
        mock_optional.is_initialized.return_value = True
        mock_model = Mock()
        mock_optional.get.return_value = mock_model

        mock_cloned = Mock()
        mock_cloned.is_initialized.return_value = False
        mock_model.clone.return_value = mock_cloned

        mock_translator_instance = Mock()
        mock_translator_instance.loadModel.return_value = mock_optional
        mock_translator.return_value = mock_translator_instance

        with pytest.raises(RuntimeError, match="Failed to clone OpenStudio model"):
            load_os_model(valid_osm_file)

    @patch("openstudio.openstudioosversion.VersionTranslator")
    def test_unexpected_exception(self, mock_translator, valid_osm_file):
        """Test handling of unexpected exceptions"""
        mock_translator.side_effect = Exception("Unexpected error")

        with pytest.raises(
            RuntimeError, match="Unexpected error loading OpenStudio model"
        ):
            load_os_model(valid_osm_file)

    # Test edge cases
    def test_file_with_mixed_case_extension(self, temp_dir):
        """Test files with mixed case extensions"""
        test_cases = [".osm", ".OSM", ".Osm", ".oSm"]

        for i, ext in enumerate(test_cases):
            file_path = os.path.join(temp_dir, f"test_model_{i}{ext}")
            with open(file_path, "w") as f:
                f.write("OS:Version,3.4.0;\n")

            with patch(
                "openstudio.openstudioosversion.VersionTranslator"
            ) as mock_translator:
                self._setup_successful_mock(mock_translator)
                result = load_os_model(file_path)
                assert result is not None

    def test_very_long_path(self, temp_dir):
        """Test handling of very long file paths"""
        # Create a deeply nested directory structure
        deep_path = temp_dir
        for i in range(10):
            deep_path = os.path.join(deep_path, f"level_{i}")

        os.makedirs(deep_path, exist_ok=True)
        file_path = os.path.join(deep_path, "test_model.osm")

        with open(file_path, "w") as f:
            f.write("OS:Version,3.4.0;\n")

        with patch(
            "openstudio.openstudioosversion.VersionTranslator"
        ) as mock_translator:
            self._setup_successful_mock(mock_translator)
            result = load_os_model(file_path)
            assert result is not None

    def _setup_successful_mock(self, mock_translator):
        """Helper method to setup successful OpenStudio mocking"""
        mock_optional = Mock()
        mock_optional.is_initialized.return_value = True
        mock_model = Mock()
        mock_optional.get.return_value = mock_model

        mock_cloned = Mock()
        mock_cloned.is_initialized.return_value = True
        mock_final_model = Mock()
        mock_cloned.to_Model.return_value = mock_final_model
        mock_model.clone.return_value = mock_cloned

        mock_translator_instance = Mock()
        mock_translator_instance.loadModel.return_value = mock_optional
        mock_translator.return_value = mock_translator_instance

        return mock_final_model
