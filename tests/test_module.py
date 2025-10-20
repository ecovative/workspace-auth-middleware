"""Sanity checks for the workspace_auth_middleware module"""

import importlib
from pathlib import Path


class TestModuleImport:
    """Test that the module can be imported"""

    def test_module_import(self):
        """Test that the module can be imported"""
        import workspace_auth_middleware

        assert workspace_auth_middleware.__name__ == "workspace_auth_middleware"

    def test_all_module_files_importable(self):
        """Test that all Python files in the module can be imported"""
        # Get the module directory
        module_dir = Path(__file__).parent.parent / "workspace_auth_middleware"

        # Find all Python files in the module directory
        python_files = []
        for file_path in module_dir.glob("*.py"):
            if (
                file_path.name != "__init__.py"
            ):  # Skip __init__.py as it's already tested
                python_files.append(file_path.stem)  # Get filename without extension

        # Try to import each file
        import_errors = []
        for file_name in python_files:
            try:
                module_name = f"workspace_auth_middleware.{file_name}"
                imported_module = importlib.import_module(module_name)
                # Verify the module was imported correctly
                assert imported_module.__name__ == module_name
            except Exception as e:
                import_errors.append(f"Failed to import {module_name}: {e}")

        # If there were any import errors, fail the test with details
        if import_errors:
            error_message = "\n".join(import_errors)
            raise AssertionError(f"Failed to import module files:\n{error_message}")

        # Verify we found at least some files to test
        assert len(python_files) > 0, "No Python files found to test"


class TestModuleAttributes:
    """Test that the module has all the attributes it should"""

    def test_module_exports_all(self):
        """Test that all module files have __all__ attribute and all values exist"""
        # Get the module directory
        module_dir = Path(__file__).parent.parent / "workspace_auth_middleware"

        # Find all Python files in the module directory
        python_files = []
        for file_path in module_dir.glob("*.py"):
            python_files.append(file_path.stem)  # Get filename without extension

        # Test each file
        export_errors = []
        for file_name in python_files:
            try:
                module_name = f"workspace_auth_middleware.{file_name}"
                imported_module = importlib.import_module(module_name)

                # Check if the module has __all__ attribute
                if not hasattr(imported_module, "__all__"):
                    export_errors.append(
                        f"{module_name} does not have __all__ attribute"
                    )
                    continue

                # Check that __all__ is a list
                if not isinstance(imported_module.__all__, list):
                    export_errors.append(
                        f"{module_name}.__all__ is not a list, got {type(imported_module.__all__)}"
                    )
                    continue

                # Check that all values in __all__ exist in the module
                missing_attributes = []
                for attr_name in imported_module.__all__:
                    if not hasattr(imported_module, attr_name):
                        missing_attributes.append(attr_name)

                if missing_attributes:
                    export_errors.append(
                        f"{module_name}.__all__ references non-existent attributes: {missing_attributes}"
                    )

            except Exception as e:
                export_errors.append(f"Failed to import {module_name}: {e}")

        # If there were any errors, fail the test with details
        if export_errors:
            error_message = "\n".join(export_errors)
            raise AssertionError(f"Module export validation failed:\n{error_message}")

        # Verify we found at least some files to test
        assert len(python_files) > 0, "No Python files found to test"
