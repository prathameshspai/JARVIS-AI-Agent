import json
import os
from typing import Dict, List, Union, Any

def _status_norm(s: str) -> str:
    """Normalizes a test status string."""
    if not s:
        return "UNKNOWN"
    
    s = s.strip().upper()
    if s.startswith("PASS"):
        return "PASS"
    if s.startswith("FAIL"):
        return "FAIL"
    if s.startswith("SKIP"):
        return "SKIP"
    return s

def _dot_to_slash_method_path(test_class: str, test_method: str) -> str:
    """Converts a dot-separated class path to a slash-separated one."""
    return f"{(test_class or '').replace('.', '/')}/{test_method or ''}"

def _load_project_root(config_path: str = "config/config.json") -> str:
    """Loads the project root directory from a config file or defaults to CWD."""
    if not os.path.exists(config_path):
        return os.getcwd()
    try:
        with open(config_path, "r") as f:
            cfg = json.load(f)
            pr = cfg.get("PROJECT_ROOT", os.getcwd())
            return pr if isinstance(pr, str) and pr.strip() else os.getcwd()
    except Exception:
        return os.getcwd()

def _normalize_path_fragment(fp: Union[str, List, tuple, None]) -> str:
    """
    Coerces a file_path to a UNIX-like string:
    - list/tuple -> join with '/'
    - other non-str -> str(value)
    - ensure no leading slash surprises
    """
    if fp is None:
        return ""
    if isinstance(fp, (list, tuple)):
        fp = "/".join(str(part).strip("/\\") for part in fp if part is not None)
    elif not isinstance(fp, str):
        fp = str(fp)
    return fp.strip()

def read_log(json_file_path: str) -> List[Dict[str, Any]]:
    """
    Loads TestNG listener JSON and enriches each record with:
    - status (normalized)
    - method_path (slash form)
    - abs_file_path (PROJECT_ROOT + file_path)
    - test_selector (Class#method)
    """
    try:
        with open(json_file_path, "r") as f:
            data = json.load(f)
            if not isinstance(data, list):
                raise ValueError("Expected JSON file to contain a list of test objects.")
    except FileNotFoundError:
        print(f"Error: The file '{json_file_path}' was not found.")
        raise
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from '{json_file_path}'.")
        raise

    project_root = _load_project_root()
    
    expected_keys = [
        "test_class", "test_method", "status", "owner", "service",
        "priority", "desc", "exception", "stacktrace", "file_path",
        "start_time", "end_time", "duration_ms"
    ]
    
    results: List[Dict] = []
    for entry in data:
        row = {k: entry.get(k) for k in expected_keys}
        row["status"] = _status_norm(row.get("status"))
        
        # Convenience/derived fields
        row["method_path"] = _dot_to_slash_method_path(
            row.get("test_class", ""), row.get("test_method", "")
        )
        
        fp = _normalize_path_fragment(row.get("file_path"))
        # if your listener emits 'src/test/java/...' this will create an absolute path
        row["abs_file_path"] = (
            os.path.normpath(os.path.join(project_root, fp)) if fp else None
        )
        
        row["test_selector"] = f"{row.get('test_class', '')}#{row.get('test_method', '')}"
        results.append(row)
        
    return results

if __name__ == "__main__":
    from pprint import pprint
    try:
        # Assuming the input file exists for the example to run
        if not os.path.exists("input/test_results.json"):
            os.makedirs("input", exist_ok=True)
            sample_data = [
                {
                    "test_class": "com.example.tests.LoginTest",
                    "test_method": "testValidLogin",
                    "status": "PASS",
                    "file_path": "src/test/java/com/example/tests/LoginTest.java"
                },
                {
                    "test_class": "com.example.tests.LoginTest",
                    "test_method": "testInvalidLogin",
                    "status": "FAIL",
                    "file_path": ["src", "test", "java", "com/example/tests/LoginTest.java"]
                },
                {
                    "test_class": "com.example.tests.FeatureTest",
                    "test_method": "testNewFeature",
                    "status": "skip",
                    "file_path": None
                }
            ]
            with open("input/test_results.json", "w") as f:
                json.dump(sample_data, f, indent=2)

        tests = read_log("input/test_results.json")
        pprint(tests[:3])
    except Exception as e:
        print(f"An error occurred during execution: {e}")