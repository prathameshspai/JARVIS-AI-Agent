import os
import sys
import re
import json
import hashlib
import subprocess
from typing import Tuple, List, Dict, Any
import litellm
from pprint import pprint

# ========================
# Config / Setup
# ========================
def load_config(path: str = "config/config.json") -> Dict[str, Any]:
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

CONFIG = load_config()
# Set the API key for the language model library
litellm.api_key = CONFIG.get("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY"))
if not litellm.api_key:
    print("FATAL: OpenAI API key not found in config/config.json or environment variables.")
    sys.exit(1)

# --- Project and Command Configuration ---
raw_project_root = CONFIG.get("PROJECT_ROOT", os.getcwd())

# Handle cases where the config might mistakenly wrap the path in a list.
if isinstance(raw_project_root, list) and raw_project_root:
    PROJECT_ROOT = raw_project_root[0]
else:
    PROJECT_ROOT = raw_project_root

# Final check to ensure PROJECT_ROOT is a valid string path.
if not isinstance(PROJECT_ROOT, str) or not os.path.isdir(PROJECT_ROOT):
    print(f"Warning: PROJECT_ROOT '{PROJECT_ROOT}' is not a valid directory. Defaulting to the current directory.")
    PROJECT_ROOT = os.getcwd()

print(f"✅ Project root configured to: {PROJECT_ROOT}")

# Default command to retry a single TestNG test method
DEFAULT_CMD = ["mvn", "-q", f"-Dtest={{test_selector}}", "test"]
AUTOMATION_SUITE_CMD: List[str] = CONFIG.get("AUTOMATION_SUITE_CMD", DEFAULT_CMD)
LLM_MODEL = CONFIG.get("LLM_MODEL", "gpt-4o-mini")

# --- Import the custom JSON log reader ---
try:
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from core.log_reader import read_log
except ImportError as e:
    print(f"FATAL: Could not import 'core.log_reader.read_log'. Ensure PYTHONPATH is set correctly. Details: {e}")
    sys.exit(1)

# ========================
# Agent State
# ========================
# This simple dictionary holds data between tool calls, preventing the need to
# pass large JSON blobs back and forth with the LLM.
AGENT_STATE = {}

# ========================
# LLM Tool Definition
# ========================
LLM_CLASSIFY_TOOL = [{
    "type": "function",
    "function": {
        "name": "return_failure_assessment",
        "description": "Return failure category and retryability for a single failed TestNG test.",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": [
                        "Assertion Failure", "Environment Issue", "Network Error",
                        "Application Logic Error", "Test Data Issue",
                        "Timeout or Sync Issue", "Unknown"
                    ]
                },
                "retryable": {"type": "boolean", "description": "True if the test failure is transient and might pass on a retry."},
                "confidence": {"type": "number", "description": "Confidence score (0.0 to 1.0) for the assessment."},
                "signals": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Keywords or phrases from the exception/stack trace that justify the category."
                },
                "reason": {"type": "string", "description": "A brief, one-sentence explanation for the decision."}
            },
            "required": ["category", "retryable", "confidence", "reason", "signals"]
        }
    }
}]

# ========================
# Helper Functions
# ========================
def _create_classification_prompt(test: Dict[str, Any]) -> str:
    """Creates a detailed prompt for the LLM to classify a single test failure."""
    exception = test.get('exception', 'No exception provided.')
    stacktrace = (test.get('stacktrace') or "No stacktrace provided.")[:1000] # Truncate for brevity
    description = test.get('desc', 'No description.')
    file_path = test.get('file_path', 'No file path.')

    return f"""
    Analyze the following failed test and classify its failure.
    <rules>
    Follow these rules in order. The first rule that matches determines the outcome.

    1.  **RETRYABLE: Transient Server/Network Errors (Highest Priority)**
    A test is ALWAYS retryable if the failure indicates a transient issue, EVEN IF it is part of an assertion error.
    - **Signals**: Any `5xx` HTTP status code (500, 502, 503, 504), `TimeoutException`, `ConnectException`, `SocketException`, `deadlock`, `Service Unavailable`.
    - **Example**: An exception like `java.lang.AssertionError: expected [200] but found [503]` IS RETRYABLE because the root cause is the `503` server error.

    2.  **NOT RETRYABLE: Deterministic Failures**
    If no transient error signals from Rule #1 are present, the test is NOT retryable.
    - **Signals**: Any `4xx` HTTP status code (400, 401, 404), `NullPointerException`, `IllegalArgumentException`, `AssertionError` comparing data (e.g., `expected [true] but found [false]`).
    </rules>

    Test Details:
    - Description: "{description}"
    - File: "{file_path}"
    - Exception: "{exception}"
    - Stack Trace Snippet:
    ---
    {stacktrace[:1000]}
    ---
    Now, call the 'return_failure_assessment' function. The 'arguments' field must be a perfectly formed, minified JSON object with no extra text or commentary. DO NOT BE CHATTY. Only return the JSON.

    """
    
def _classify_single_test(test: Dict[str, Any]) -> Dict[str, Any]:
    """Uses the LLM to classify a single failed test."""
    print(f"🧠 Classifying test: {test['test_selector']}...")
    prompt = _create_classification_prompt(test)
    raw_arguments = "" # Variable to hold the raw response for debugging
    try:
        response = litellm.completion(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            tools=LLM_CLASSIFY_TOOL,
            tool_choice={"type": "function", "function": {"name": "return_failure_assessment"}},
            temperature=0
        )
        tool_call = response.choices[0].message.tool_calls[0]
        raw_arguments = tool_call.function.arguments

        # Step 1: Extract the JSON object from the raw response.
        start_index = raw_arguments.find('{')
        end_index = raw_arguments.rfind('}')
        
        if start_index != -1 and end_index != -1 and end_index > start_index:
            json_string = raw_arguments[start_index : end_index + 1]
            
            # **Step 2: Clean the extracted string for common LLM errors (like trailing commas).**
            # This regex removes commas that are immediately followed by a '}' or ']'.
            cleaned = re.sub(r',\s*([\}\]])', r'\1', json_string)     # your current line
            cleaned = re.sub(r',\s*"\s*\}', '}', cleaned)             # fix …,"}
            cleaned = re.sub(r'"\s*$', '', cleaned)                   # drop dangling quote at end
            assessment = json.loads(cleaned)
            
            print(f"   - Result: Category='{assessment.get('category')}', Retryable={assessment.get('retryable')}")
            return assessment
        else:
            raise ValueError("Could not find a valid JSON object in the LLM's response.")

    except json.JSONDecodeError as e:
        print(f"   - 🚨 JSON DECODE ERROR: The LLM returned a malformed response that could not be cleaned.")
        print(f"   - Error Details: {e}")
        print(f"   - ▼▼▼ RAW LLM RESPONSE ▼▼▼")
        print(raw_arguments)
        print(f"   - ▲▲▲ END RAW RESPONSE ▲▲▲")
        return {
            "category": "Unknown", "retryable": False, "confidence": 0.0,
            "reason": "Failed to parse malformed JSON response from LLM.", "signals": [str(e)]
        }
    except Exception as e:
        print(f"   - 🚨 An unexpected error occurred during classification: {e}")
        return {
            "category": "Unknown", "retryable": False, "confidence": 0.0,
            "reason": "An unexpected exception occurred.", "signals": [str(e)]
        }

def _run_single_test_command(test_selector: str) -> bool:
    """Executes a shell command to retry a single test and returns its success status."""
    command = [part.format(test_selector=test_selector) for part in AUTOMATION_SUITE_CMD]
    print(f"   - Executing retry command: {' '.join(command)}")
    try:
        result = subprocess.run(
            command, cwd=PROJECT_ROOT, capture_output=True, text=True, check=False
        )
        if result.returncode == 0:
            print("   - ✅ Retry PASSED")
            return True
        else:
            print(f"   - ❌ Retry FAILED (Exit Code: {result.returncode})")
            return False
    except FileNotFoundError:
        print(f"   - 🚨 Error: Command '{command[0]}' not found. Is Maven installed and in your PATH?")
        return False
    except Exception as e:
        print(f"   - 🚨 An unexpected error occurred while running the test: {e}")
        return False

# ========================
# Tool Functions for the Agent
# ========================
def tool_get_failed_tests(json_path: str) -> str:
    """
    Tool: Loads all test results, filters for failures, and saves them to an internal state.
    Returns a summary message for the LLM.
    """
    print("\n🛠️ Running Tool: get_failed_tests")
    try:
        all_tests = read_log(json_path)
        failed_tests = [t for t in all_tests if t.get("status") == "FAIL"]
        
        # **STATE CHANGE**: Store the full data internally
        AGENT_STATE['failed_tests'] = failed_tests
        
        summary = f"Successfully found {len(failed_tests)} failed tests out of {len(all_tests)} total. Ready for categorization."
        print(f"   - {summary}")
        return summary
    except FileNotFoundError:
        return f"Error: The file '{json_path}' was not found."
    except Exception as e:
        return f"Error reading or parsing log file: {e}"

def tool_categorize_failures() -> str:
    """
    Tool: Retrieves failed tests from the internal state, classifies them using an LLM,
    and saves the results back to the state. Returns a summary.
    """
    print("\n🛠️ Running Tool: categorize_failures")
    failed_tests = AGENT_STATE.get('failed_tests')
    if not failed_tests:
        return "Error: Could not find any failed tests in the state. Please run 'get_failed_tests' first."
        
    categorized_results = []
    for test in failed_tests:
        assessment = _classify_single_test(test)
        categorized_results.append({**test, "assessment": assessment})

    # **STATE CHANGE**: Store the categorized results
    AGENT_STATE['categorized_tests'] = categorized_results
    
    summary = f"Successfully categorized {len(categorized_results)} failed tests. Ready for retry."
    print(f"   - {summary}")
    return summary

def tool_retry_tests(max_retries) -> str:
    """
    Tool: Retrieves categorized tests from the state, retries the ones marked 'retryable',
    and updates their status in the state. Returns a summary of the retry operation.
    """
    max_retries=3
    print(f"\n🛠️ Running Tool: retry_tests (Max Retries: {max_retries})")
    categorized_tests = AGENT_STATE.get('categorized_tests')
    if not categorized_tests:
        return "Error: Could not find any categorized tests in the state. Please run 'categorize_failures' first."

    tests_to_retry = [t for t in categorized_tests if t.get("assessment", {}).get("retryable")]
    
    if not tests_to_retry:
        summary = "No tests were marked as retryable. Nothing to do."
        print(f"   - {summary}")
        AGENT_STATE['final_results'] = categorized_tests
        return summary

    print(f"   - Found {len(tests_to_retry)} tests to retry.")
    passed_on_retry = 0
    for test in categorized_tests:
        if test in tests_to_retry:
            print(f"  - Attempting to retry '{test['test_selector']}'...")
            for attempt in range(max_retries):
                print(f"   - Attempt {attempt + 1} of {max_retries}...")
                success = _run_single_test_command(test['test_selector'])
                if success:
                    test["status"] = "PASSED_ON_RETRY"
                    passed_on_retry += 1
                    break
    
    # **STATE CHANGE**: Store the final results after retries
    AGENT_STATE['final_results'] = categorized_tests
    
    summary = f"Retry process complete. {passed_on_retry} out of {len(tests_to_retry)} retryable tests passed."
    print(f"   - {summary}")
    return summary

def tool_terminate(message: str) -> str:
    """Tool: A final function to end the execution loop."""
    print(f"\n🏁 Agent is terminating. Reason: {message}")
    # You could add final reporting here using AGENT_STATE['final_results']
    return message

def _write_final_results_to_json(input_path: str, output_path: str):
    """
    Copies the input JSON file to a new location and updates the status of
    tests that passed on retry using a reliable matching method.
    """
    print(f"\n📝 Writing final results to {output_path}...")
    try:
        # Load the original test results from the input file
        with open(input_path, 'r') as f:
            original_data = json.load(f)

        # Get the final results from the agent's internal state
        final_results = AGENT_STATE.get('final_results', [])
        
        # If there are no final results, there's nothing to update.
        if not final_results:
            print("   - No final results found in agent state. Copying file without changes.")
            with open(output_path, 'w') as f:
                json.dump(original_data, f, indent=2)
            return

        # Create a lookup dictionary for updated statuses.
        # The key is a tuple of (class_name, method_name) for robust matching.
        updated_statuses = {
            (test['test_class'], test['test_method']): test['status']
            for test in final_results
            if test.get('status') == 'PASSED_ON_RETRY'
        }
        
        if not updated_statuses:
            print("   - No tests passed on retry. Copying file without changes.")
            with open(output_path, 'w') as f:
                json.dump(original_data, f, indent=2)
            return

        # Iterate through the original data and apply updates
        update_count = 0
        updated_data = original_data.copy()
        for test in updated_data:
            # Create the same tuple key from the original data to find a match
            lookup_key = (test.get('test_class'), test.get('test_method'))
            if lookup_key in updated_statuses:
                test['status'] = updated_statuses[lookup_key]
                update_count += 1

        # Write the modified data to the output file
        with open(output_path, 'w') as f:
            json.dump(updated_data, f, indent=2)

        if update_count > 0:
            print(f"   - Successfully wrote {update_count} test status updates to '{output_path}'.")
        else:
            # This warning helps debug if updates were expected but not applied
            print(f"   - Warning: Found {len(updated_statuses)} tests that passed on retry, but couldn't find matching tests to update in the output file.")

    except FileNotFoundError:
        print(f"   - 🚨 Error: Input file not found at '{input_path}'.")
    except json.JSONDecodeError:
        print(f"   - 🚨 Error: Could not parse JSON from '{input_path}'.")
    except KeyError as e:
        print(f"   - 🚨 Error: A required key ({e}) was missing from a test record, cannot process updates.")
    except Exception as e:
        print(f"   - 🚨 An unexpected error occurred while writing the file: {e}")



# ========================
# Main Agent Execution Loop
# ========================
if __name__ == "__main__":
    # 1. Define all the tools the agent can use. Notice the parameters have been updated.
    tools = [
        {
            "type": "function", "function": {
                "name": "get_failed_tests",
                "description": "Load FAILED tests from a TestNG JSON file and store them for the next step.",
                "parameters": {"type": "object", "properties": {"json_path": {"type": "string", "description": "The path to the input JSON file."}}, "required": ["json_path"]}
            }
        },
        {
            "type": "function", "function": {
                "name": "categorize_failures",
                "description": "Categorize the failed tests that were loaded in the previous step.",
                "parameters": {"type": "object", "properties": {}} # No arguments needed
            }
        },
        {
            "type": "function", "function": {
                "name": "retry_tests",
                "description": "Retry tests previously marked as 'retryable' and update their status.",
                "parameters": {"type": "object", "properties": {"max_retries": {"type": "integer", "default": 1}}, "required": []}
            }
        },
        {
            "type": "function", "function": {
                "name": "terminate",
                "description": "Terminate the run once the workflow is complete.",
                "parameters": {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]}
            }
        }
    ]

    # 2. Map tool names to their actual Python functions.
    tool_functions = {
        "get_failed_tests": tool_get_failed_tests,
        "categorize_failures": tool_categorize_failures,
        "retry_tests": tool_retry_tests,
        "terminate": tool_terminate,
    }

    # 3. Set up the initial conversation for the agent.
    messages = [
        {"role": "system", "content": "You are an expert SDET assistant. Your goal is to analyze test results, identify flaky tests that can be retried, execute the retries, and report the final outcome. Follow the steps logically: get failures, categorize them, retry the flaky ones, and then terminate."},
        {"role": "user", "content": "Please process the test results from 'input/test_results.json', identify and retry any flaky tests, and then provide a final report."},
    ]

    # 4. Start the execution loop.
    print("🚀 Starting AI SDET Agent...")
    while True:
        response = litellm.completion(model=LLM_MODEL, messages=messages, tools=tools)
        response_message = response.choices[0].message

        if response_message.tool_calls:
            messages.append(response_message) 
            
            for tool_call in response_message.tool_calls:
                function_name = tool_call.function.name
                if function_name == "terminate":
                    print("\n✅ Workflow complete.")
                    final_message = json.loads(tool_call.function.arguments).get("message", "Done.")
                    _write_final_results_to_json(
                            input_path="input/test_results.json",
                            output_path="outputs/ai_test_analysis.json"
                        )
                    tool_terminate(final_message)
                    sys.exit(0) 

                function_to_call = tool_functions.get(function_name)
                if function_to_call:
                    try:
                        function_args = json.loads(tool_call.function.arguments)
                        function_response = function_to_call(**function_args)
                        
                        messages.append({
                            "tool_call_id": tool_call.id,
                            "role": "tool",
                            "name": function_name,
                            "content": function_response, # Now passing a simple string summary
                        })
                    except Exception as e:
                        print(f"Error executing tool {function_name}: {e}")
                        messages.append({
                            "tool_call_id": tool_call.id,
                            "role": "tool",
                            "name": function_name,
                            "content": f"Error: {e}",
                        })
                else:
                    print(f"Error: LLM tried to call unknown function '{function_name}'")
        else:
            print("\nLLM did not call a function. Final response:")
            pprint(response_message.content or "No final message.")
            break