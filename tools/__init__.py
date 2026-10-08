from tools.artifact import read_artifact, search_artifact
from tools.reading import get_file_info, read_file
from .discovery import list_directory, search_content, search_files
from .shell import run_terminal

TOOLS = [search_files, run_terminal, list_directory, search_content, read_file, get_file_info, search_artifact, read_artifact]
