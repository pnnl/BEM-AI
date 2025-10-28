import os


def verify_directory_and_json_files(directory_path):
    # Check if the directory exists and there are .jsons
    if not os.path.isdir(directory_path):
        print(f"The directory '{directory_path}' does not exist.")
        return False

    # Get a list of all files in the directory
    files_in_directory = os.listdir(directory_path)

    # Filter out files that end with '.json'
    json_files = [file for file in files_in_directory if file.endswith('.json')]

    # Check if there are any .json files
    if not json_files:
        print(f"No .json files found in the directory '{directory_path}'.")
        return False

    print(f"The directory '{directory_path}' exists and contains the following .json files:")
    for json_file in json_files:
        print(f" - {json_file}")

    return True