import os

import openstudio


def load_os_model(model_path: str):
    """
    Function to load an openstudio model from a file directory and return a copy of the model

    :param model_path: str, local directory to the model
    :return: openstudio model
    :raises FileNotFoundError: If the file doesn't exist or is not a valid .osm file
    :raises ValueError: If the model_path is not a string or is empty
    :raises RuntimeError: If the model fails to load or clone
    """

    # Input validation
    if not isinstance(model_path, str):
        raise ValueError("model_path must be a string")

    if not model_path or model_path.isspace():
        raise ValueError("model_path cannot be empty or whitespace")

    # Normalize the path to handle different path separators and resolve relative paths
    normalized_path = os.path.normpath(os.path.abspath(model_path.strip()))

    # Check if file exists
    if not os.path.exists(normalized_path):
        raise FileNotFoundError(f"File does not exist: {normalized_path}")

    # Check if it's actually a file (not a directory)
    if not os.path.isfile(normalized_path):
        raise FileNotFoundError(f"Path is not a file: {normalized_path}")

    # Check file extension (case-insensitive)
    file_extension = os.path.splitext(normalized_path)[1].lower()
    if file_extension != ".osm":
        raise FileNotFoundError(f"File must have .osm extension, got: {file_extension}")

    # Check if file is readable
    if not os.access(normalized_path, os.R_OK):
        raise FileNotFoundError(f"File is not readable: {normalized_path}")

    # Check if file is not empty
    try:
        file_size = os.path.getsize(normalized_path)
        if file_size == 0:
            raise FileNotFoundError(f"File is empty: {normalized_path}")
    except OSError as e:
        raise FileNotFoundError(
            f"Cannot access file size: {normalized_path}. Error: {str(e)}"
        )

    try:
        # Load the OpenStudio model
        translator = openstudio.openstudioosversion.VersionTranslator()

        # Load model and check if loading was successful
        optional_model = translator.loadModel(normalized_path)
        if not optional_model.is_initialized():
            raise RuntimeError(
                f"Failed to load OpenStudio model from: {normalized_path}"
            )

        model = optional_model.get()

        # Create and return a copy of the model
        cloned_model = model.clone()
        if not cloned_model.is_initialized():
            raise RuntimeError(
                f"Failed to clone OpenStudio model from: {normalized_path}"
            )

        model_copy = cloned_model.to_Model()

        return model_copy

    except Exception as e:
        # Re-raise specific exceptions we've already handled
        if isinstance(e, (FileNotFoundError, ValueError, RuntimeError)):
            raise

        # Handle any other unexpected exceptions
        raise RuntimeError(
            f"Unexpected error loading OpenStudio model from {normalized_path}: {str(e)}"
        )
