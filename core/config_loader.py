import os
import sys
import json
from typing import List, Dict, Any

class AppConfig:
    """
    Handles loading, validation, and access for all application configurations.
    """
    def __init__(self, path: str = "config/config.json"):
        """
        Initializes the configuration object by loading from a JSON file.

        Args:
            path (str): The path to the configuration JSON file.
        
        Raises:
            ValueError: If a critical configuration value is missing or invalid.
        """
        self.config_data = self._load_from_json(path)
        
        # Validate critical configurations upon initialization
        if not self.api_key:
            raise ValueError("OpenAI API key not found. Please set it in config/config.json or as an environment variable.")
        if not os.path.isdir(self.project_root):
            print(f"Warning: PROJECT_ROOT '{self.project_root}' is not a valid directory. Defaulting to current directory.")
            self._project_root = os.getcwd()

    @staticmethod
    def _load_from_json(path: str) -> Dict[str, Any]:
        """Loads configuration from a JSON file."""
        if not os.path.exists(path):
            print(f"Warning: Config file not found at {path}. Using defaults.")
            return {}
        try:
            with open(path, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(f"Error: Could not decode JSON from {path}.")
            return {}

    @property
    def api_key(self) -> str:
        """Returns the OpenAI API key from config or environment variables."""
        return self.config_data.get("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY"))

    @property
    def project_root(self) -> str:
        """
        Parses and validates the project root directory from the config.
        Defaults to the current working directory if not specified or invalid.
        """
        if not hasattr(self, '_project_root'):
            raw_path = self.config_data.get("PROJECT_ROOT", os.getcwd())
            # Handle case where config might be a list
            self._project_root = raw_path[0] if isinstance(raw_path, list) and raw_path else raw_path
        return self._project_root

    @property
    def automation_suite_cmd(self) -> List[str]:
        """Returns the command for running the automation test suite."""
        return self.config_data.get("AUTOMATION_SUITE_CMD", ["mvn", "-q", "-Dtest={test_selector}", "test"])

    @property
    def llm_model(self) -> str:
        """Returns the configured LLM model name."""
        return self.config_data.get("LLM_MODEL", "gpt-4o-mini")