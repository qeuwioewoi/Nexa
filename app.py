#!/usr/bin/env python3

import os
import sys
import json
import subprocess
import shlex
import xml.etree.ElementTree as ET
import re # Added for search_files regex
import ast # Added for list_code_definition_names (Python only)
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from openai import OpenAI, APIError
from pydantic import BaseModel # Keep for potential future structured data
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
import gradio as gr

# Initialize Rich console
console = Console()

# --- Configuration Loading ---
def load_config(config_file: str = "coder.config") -> dict:
    """Load configuration from a JSON file."""
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            config_data = json.load(f)
            # Ensure essential keys are present
            if "system_PROMPT" not in config_data:
                raise ValueError("Missing 'system_PROMPT' in config.")
            if "model_name" not in config_data:
                raise ValueError("Missing 'model_name' in config.")
            return config_data
    except FileNotFoundError:
        console.print(f"[red]✗ Error:[/red] Configuration file '{config_file}' not found.", style="bold red")
        sys.exit(1)
    except json.JSONDecodeError:
        console.print(f"[red]✗ Error:[/red] Invalid JSON in configuration file '{config_file}'.", style="bold red")
        sys.exit(1)
    except ValueError as e:
        console.print(f"[red]✗ Error:[/red] Configuration error: {e}", style="bold red")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]✗ Error:[/red] Failed to load config: {e}", style="bold red")
        sys.exit(1)

config = load_config()

# --- OpenAI Client Setup ---
load_dotenv()
API_KEY = os.getenv("OPENROUTER_API_KEY") or os.getenv("API_KEY") # Allow fallback
if not API_KEY:
    console.print("[red]✗ Error:[/red] API key not found. Set OPENROUTER_API_KEY or API_KEY in your .env file.", style="bold red")
    sys.exit(1)

client = OpenAI(
    api_key=API_KEY,
    base_url=config.get("api_base_url", "https://openrouter.ai/api/v1")
)
model_name = config.get("model_name")
system_prompt = config.get("system_PROMPT")
# Add current working directory to system prompt if placeholder exists
cwd = Path.cwd()
system_prompt = system_prompt.replace("${cwd.toPosix()}", cwd.as_posix())


# --- Pydantic Models (Kept for potential future use, less central now) ---
class FileToCreate(BaseModel):
    path: str
    content: str

class FileToEdit(BaseModel):
    path: str
    original_snippet: str
    new_snippet: str

class AssistantResponseStructure(BaseModel): # Renamed for clarity
    assistant_reply: str
    files_to_create: Optional[List[FileToCreate]] = None
    files_to_edit: Optional[List[FileToEdit]] = None

# --- Helper Functions ---
def normalize_path(path_str: str) -> Path:
    """Return a resolved Path object relative to the current working directory."""
    # Security: Prevent escaping the current working directory using '..'
    try:
        resolved_path = (cwd / path_str).resolve(strict=False) # Allow resolving non-existent paths for writing
        # Check if the resolved path is within the current working directory or is the CWD itself
        if cwd not in resolved_path.parents and resolved_path != cwd:
             # Further check to prevent tricky paths like '/foo/../bar' resolving outside cwd
             if not str(resolved_path).startswith(str(cwd)):
                 raise ValueError(f"Path '{path_str}' attempts to escape the current working directory.")
        return resolved_path
    except Exception as e: # Catch potential resolution errors
        raise ValueError(f"Invalid or forbidden path '{path_str}': {e}")


def _read_local_file_impl(file_path: Path) -> str:
    """Reads a file, raising FileNotFoundError if it doesn't exist."""
    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        raise IOError(f"Failed to read file '{file_path}': {e}")

def _write_to_file_impl(file_path: Path, content: str):
    """Creates or overwrites a file with content."""
    try:
        # TODO: Implement Pre-Commit Validation Hook (NPCVH) here
        # - Run linters, formatters, type checkers on 'content' before writing.
        # - If validation fails, raise an exception instead of writing.
        console.print(f"[yellow]ℹ[/yellow] Attempting to write to '[cyan]{file_path}[/cyan]'...")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        console.print(f"[green]✓[/green] Successfully wrote to '[cyan]{file_path}[/cyan]'")
    except IOError as e:
        console.print(f"[red]✗ Error:[/red] Failed to write file '{file_path}': {e}", style="bold red")
        raise # Re-raise the exception to be caught by the tool executor
    except Exception as e:
        console.print(f"[red]✗ Error:[/red] An unexpected error occurred writing file '{file_path}': {e}", style="bold red")
        raise IOError(f"Unexpected error writing file '{file_path}': {e}")


def _execute_command_impl(command: str, requires_approval: bool) -> Tuple[int, str, str]:
    """Executes a shell command safely."""
    console.print(f"[yellow]ℹ[/yellow] Proposed command: [bold magenta]{command}[/bold magenta]")

    # --- CRITICAL SAFETY CHECK ---
    confirm = "y" # Default to yes for non-approval commands
    if requires_approval:
         try:
              # In a real UI, this would be a proper confirmation dialog
              confirm = input(f"Requires approval. Execute? (y/N): ").lower().strip()
         except EOFError: # Handle non-interactive environments
              confirm = "n"

    if confirm != 'y':
        console.print("[yellow]⚠[/yellow] Command execution skipped by user.", style="yellow")
        raise PermissionError("Command execution denied by user.")

    console.print(f"[yellow]Executing...[/yellow]")
    try:
        # Use shlex.split for better handling of quotes and spaces
        # Run in the current working directory
        process = subprocess.run(
            shlex.split(command),
            capture_output=True,
            text=True,
            check=False, # Don't raise exception on non-zero exit code, handle it below
            cwd=cwd,
            timeout=120 # Add a timeout (e.g., 2 minutes)
        )
        console.print(f"[green]✓[/green] Command finished with exit code: {process.returncode}")
        if process.stdout:
            console.print(Panel(process.stdout, title="stdout", border_style="green"))
        if process.stderr:
            console.print(Panel(process.stderr, title="stderr", border_style="red"))
        return process.returncode, process.stdout, process.stderr
    except FileNotFoundError:
        err_msg = f"Command not found or not executable: {shlex.split(command)[0]}"
        console.print(f"[red]✗ Error:[/red] {err_msg}", style="bold red")
        return -1, "", err_msg # Use -1 to indicate execution failure
    except subprocess.TimeoutExpired:
        err_msg = f"Command timed out after 120 seconds: {command}"
        console.print(f"[red]✗ Error:[/red] {err_msg}", style="bold red")
        return -1, "", err_msg
    except Exception as e:
        err_msg = f"Failed to execute command '{command}': {e}"
        console.print(f"[red]✗ Error:[/red] {err_msg}", style="bold red")
        return -1, "", err_msg

# --- Tool Implementation Functions ---

def _tool_read_file(params: Dict[str, str]) -> str:
    """Implements the 'read_file' tool."""
    path_str = params.get("path")
    if not path_str:
        return "<tool_result tool_name=\"read_file\"><status>error</status><message>Missing 'path' parameter.</message></tool_result>"
    try:
        file_path = normalize_path(path_str)
        content = _read_local_file_impl(file_path)
        return f"<tool_result tool_name=\"read_file\"><status>success</status><content>{ET.escape(content)}</content></tool_result>"
    except (FileNotFoundError, ValueError, IOError) as e:
        return f"<tool_result tool_name=\"read_file\"><status>error</status><message>{ET.escape(str(e))}</message></tool_result>"

def _tool_write_to_file(params: Dict[str, str]) -> str:
    """Implements the 'write_to_file' tool."""
    path_str = params.get("path")
    content = params.get("content")
    if path_str is None or content is None: # Check for None explicitly
        return "<tool_result tool_name=\"write_to_file\"><status>error</status><message>Missing 'path' or 'content' parameter.</message></tool_result>"
    try:
        file_path = normalize_path(path_str)
        _write_to_file_impl(file_path, content)
        # TODO: Implement Post-Commit Validation (NATE) - e.g., trigger tests if applicable
        return f"<tool_result tool_name=\"write_to_file\"><status>success</status><message>File '{file_path.relative_to(cwd)}' written successfully.</message></tool_result>"
    except (ValueError, IOError, PermissionError) as e: # Catch PermissionError too
        return f"<tool_result tool_name=\"write_to_file\"><status>error</status><message>{ET.escape(str(e))}</message></tool_result>"

def _tool_execute_command(params: Dict[str, str]) -> str:
    """Implements the 'execute_command' tool."""
    command = params.get("command")
    requires_approval_str = params.get("requires_approval", "false").lower() # Default to false
    if not command:
        return "<tool_result tool_name=\"execute_command\"><status>error</status><message>Missing 'command' parameter.</message></tool_result>"

    requires_approval = requires_approval_str == "true"

    try:
        exit_code, stdout, stderr = _execute_command_impl(command, requires_approval)
        # TODO: Implement Corrective Action Generator (NCAG) based on exit_code/stderr
        return (
            f"<tool_result tool_name=\"execute_command\">"
            f"<status>{'success' if exit_code == 0 else 'error'}</status>"
            f"<exit_code>{exit_code}</exit_code>"
            f"<stdout>{ET.escape(stdout)}</stdout>"
            f"<stderr>{ET.escape(stderr)}</stderr>"
            f"</tool_result>"
        )
    except PermissionError as e: # Catch denial
         return f"<tool_result tool_name=\"execute_command\"><status>skipped</status><message>{ET.escape(str(e))}</message></tool_result>"
    except Exception as e: # Catch other execution errors
        return f"<tool_result tool_name=\"execute_command\"><status>error</status><message>Execution failed: {ET.escape(str(e))}</message></tool_result>"

def _tool_replace_in_file(params: Dict[str, str]) -> str:
    """Implements the 'replace_in_file' tool using the SEARCH/REPLACE block format."""
    path_str = params.get("path")
    diff_content = params.get("diff")

    if not path_str or diff_content is None:
        return "<tool_result tool_name=\"replace_in_file\"><status>error</status><message>Missing 'path' or 'diff' parameter.</message></tool_result>"

    try:
        file_path = normalize_path(path_str)
        original_content = _read_local_file_impl(file_path)
        current_content = original_content
        replacements_made = 0
        errors = []

        # Regex to find SEARCH/REPLACE blocks
        block_pattern = re.compile(r"<<<<<<< SEARCH\s*([\s\S]*?)\s*=======\s*([\s\S]*?)\s*>>>>>>> REPLACE", re.MULTILINE)

        for match in block_pattern.finditer(diff_content):
            search_block = match.group(1).strip('\r\n') # Strip leading/trailing newlines only
            replace_block = match.group(2).strip('\r\n')

            # Adhere to "first match occurrence" rule
            if search_block in current_content:
                # Perform exact, one-time replacement
                current_content = current_content.replace(search_block, replace_block, 1)
                replacements_made += 1
                console.print(f"[green]✓[/green] Applied replacement block in '[cyan]{file_path}[/cyan]'")
            else:
                error_msg = f"SEARCH block not found exactly in file '{file_path.relative_to(cwd)}'. Block:\n{search_block}"
                console.print(f"[yellow]⚠[/yellow] {error_msg}", style="yellow")
                errors.append(error_msg)

        if replacements_made > 0 and not errors:
            # Write the modified content back to the file
            _write_to_file_impl(file_path, current_content)
            return f"<tool_result tool_name=\"replace_in_file\"><status>success</status><message>Applied {replacements_made} replacement(s) to '{file_path.relative_to(cwd)}'.</message></tool_result>"
        elif replacements_made > 0 and errors:
             # Partial success - some blocks applied, some failed
             _write_to_file_impl(file_path, current_content) # Write the partially modified file
             error_summary = "; ".join(errors)
             return f"<tool_result tool_name=\"replace_in_file\"><status>partial_error</status><message>Applied {replacements_made} replacement(s) but encountered errors: {ET.escape(error_summary)}</message></tool_result>"
        elif not errors:
             # No replacements made, but no explicit errors (maybe blocks were empty or already matched replace?)
             return f"<tool_result tool_name=\"replace_in_file\"><status>no_change</status><message>No applicable SEARCH blocks found or no changes needed in '{file_path.relative_to(cwd)}'.</message></tool_result>"
        else:
            # No replacements made, only errors
            error_summary = "; ".join(errors)
            return f"<tool_result tool_name=\"replace_in_file\"><status>error</status><message>Failed to apply replacements: {ET.escape(error_summary)}</message></tool_result>"

    except (FileNotFoundError, ValueError, IOError, PermissionError) as e:
        return f"<tool_result tool_name=\"replace_in_file\"><status>error</status><message>{ET.escape(str(e))}</message></tool_result>"
    except Exception as e:
        return f"<tool_result tool_name=\"replace_in_file\"><status>error</status><message>Unexpected error during replace: {ET.escape(str(e))}</message></tool_result>"


def _tool_search_files(params: Dict[str, str]) -> str:
    """Implements the 'search_files' tool."""
    path_str = params.get("path", ".") # Default to current directory
    regex_pattern = params.get("regex")
    file_pattern = params.get("file_pattern", "*") # Default to all files

    if not regex_pattern:
        return "<tool_result tool_name=\"search_files\"><status>error</status><message>Missing 'regex' parameter.</message></tool_result>"

    try:
        search_path = normalize_path(path_str)
        if not search_path.is_dir():
            raise ValueError(f"Path '{path_str}' is not a valid directory.")

        compiled_regex = re.compile(regex_pattern)
        matches = []
        max_matches = 100 # Limit the number of matches to avoid overwhelming output
        match_count = 0

        console.print(f"[yellow]ℹ[/yellow] Searching in '[cyan]{search_path}[/cyan]' for regex '[magenta]{regex_pattern}[/magenta]' in files matching '[blue]{file_pattern}[/blue]'...")

        # Use rglob for recursive searching with glob pattern
        for file_path in search_path.rglob(file_pattern):
            if file_path.is_file():
                try:
                    content = _read_local_file_impl(file_path)
                    # Find all matches in the file content
                    for match in compiled_regex.finditer(content):
                        if match_count >= max_matches:
                            break
                        # Provide some context around the match
                        start, end = match.span()
                        context_start = max(0, start - 50)
                        context_end = min(len(content), end + 50)
                        context = content[context_start:context_end].replace('\n', ' ') # Simple context
                        matches.append({
                            "file": str(file_path.relative_to(cwd)),
                            "match": match.group(0),
                            "context": context
                        })
                        match_count += 1
                except (IOError, UnicodeDecodeError) as e:
                    console.print(f"[yellow]⚠[/yellow] Skipping file '{file_path}': {e}", style="yellow")
                except Exception as e:
                     console.print(f"[red]✗ Error:[/red] Unexpected error processing file '{file_path}': {e}", style="bold red")
            if match_count >= max_matches:
                console.print(f"[yellow]⚠[/yellow] Reached maximum match limit ({max_matches}).", style="yellow")
                break

        # Format results as XML
        results_xml = "".join([
            f"<match><file>{ET.escape(m['file'])}</file><text>{ET.escape(m['match'])}</text><context>{ET.escape(m['context'])}</context></match>"
            for m in matches
        ])

        status = "success" if matches or match_count == 0 else "error" # Consider no matches success
        message = f"Found {len(matches)} match(es)."
        if match_count >= max_matches:
            message += f" Stopped at maximum limit ({max_matches})."

        return f"<tool_result tool_name=\"search_files\"><status>{status}</status><message>{message}</message><matches>{results_xml}</matches></tool_result>"

    except (ValueError, IOError) as e:
        return f"<tool_result tool_name=\"search_files\"><status>error</status><message>{ET.escape(str(e))}</message></tool_result>"
    except re.error as e:
         return f"<tool_result tool_name=\"search_files\"><status>error</status><message>Invalid regex pattern: {ET.escape(str(e))}</message></tool_result>"
    except Exception as e:
        return f"<tool_result tool_name=\"search_files\"><status>error</status><message>Unexpected error during search: {ET.escape(str(e))}</message></tool_result>"


def _tool_list_files(params: Dict[str, str]) -> str:
    """Implements the 'list_files' tool."""
    path_str = params.get("path", ".") # Default to current directory
    recursive_str = params.get("recursive", "false").lower()
    recursive = recursive_str == "true"

    try:
        list_path = normalize_path(path_str)
        if not list_path.is_dir():
            raise ValueError(f"Path '{path_str}' is not a valid directory.")

        console.print(f"[yellow]ℹ[/yellow] Listing files in '[cyan]{list_path}[/cyan]' (Recursive: {recursive})...")
        files = []
        dirs = []
        max_items = 500 # Limit output size
        item_count = 0

        if recursive:
            for item in sorted(list_path.rglob('*')):
                if item_count >= max_items: break
                relative_path = str(item.relative_to(cwd))
                if item.is_file():
                    files.append(relative_path)
                    item_count += 1
                elif item.is_dir():
                    dirs.append(relative_path + "/") # Add trailing slash for dirs
                    item_count += 1
        else:
            for item in sorted(list_path.iterdir()):
                 if item_count >= max_items: break
                 relative_path = str(item.relative_to(cwd))
                 if item.is_file():
                     files.append(relative_path)
                     item_count += 1
                 elif item.is_dir():
                     dirs.append(relative_path + "/")
                     item_count += 1

        files_xml = "".join([f"<file>{ET.escape(f)}</file>" for f in files])
        dirs_xml = "".join([f"<directory>{ET.escape(d)}</directory>" for d in dirs])

        message = f"Listed {len(files)} files and {len(dirs)} directories."
        if item_count >= max_items:
            message += f" Stopped at maximum limit ({max_items})."

        return f"<tool_result tool_name=\"list_files\"><status>success</status><message>{message}</message><files>{files_xml}</files><directories>{dirs_xml}</directories></tool_result>"

    except (ValueError, IOError) as e:
        return f"<tool_result tool_name=\"list_files\"><status>error</status><message>{ET.escape(str(e))}</message></tool_result>"
    except Exception as e:
        return f"<tool_result tool_name=\"list_files\"><status>error</status><message>Unexpected error listing files: {ET.escape(str(e))}</message></tool_result>"


def _tool_list_code_definition_names(params: Dict[str, str]) -> str:
    """
    Implements 'list_code_definition_names'.
    **WARNING:** This implementation ONLY reliably works for Python files using the 'ast' module.
    For other languages, using `execute_command` with tools like `ctags` is recommended.
    """
    path_str = params.get("path", ".") # Default to current directory

    try:
        target_path = normalize_path(path_str)
        if not target_path.is_dir():
            raise ValueError(f"Path '{path_str}' is not a valid directory.")

        console.print(f"[yellow]ℹ[/yellow] Listing definitions in '[cyan]{target_path}[/cyan]' (Python files only)...")
        definitions = []
        max_defs = 200
        def_count = 0
        processed_files = 0
        skipped_files = 0

        for item in target_path.rglob('*.py'): # Only process .py files
             if def_count >= max_defs: break
             if item.is_file():
                 processed_files += 1
                 try:
                     content = _read_local_file_impl(item)
                     tree = ast.parse(content)
                     for node in ast.walk(tree):
                         if def_count >= max_defs: break
                         name = None
                         def_type = None
                         if isinstance(node, ast.FunctionDef):
                             name = node.name
                             def_type = "function"
                         elif isinstance(node, ast.AsyncFunctionDef):
                             name = node.name
                             def_type = "async_function"
                         elif isinstance(node, ast.ClassDef):
                             name = node.name
                             def_type = "class"
                         # Could add ast.Assign for top-level variables if needed

                         if name and def_type:
                             definitions.append({
                                 "file": str(item.relative_to(cwd)),
                                 "name": name,
                                 "type": def_type
                             })
                             def_count += 1
                 except SyntaxError:
                     console.print(f"[yellow]⚠[/yellow] Syntax error parsing Python file: '{item}'", style="yellow")
                 except Exception as e:
                     console.print(f"[red]✗ Error:[/red] Could not process Python file '{item}': {e}", style="bold red")
             if def_count >= max_defs:
                 console.print(f"[yellow]⚠[/yellow] Reached maximum definition limit ({max_defs}).", style="yellow")
                 break
        # Check for non-python files to inform the user about the limitation
        for item in target_path.rglob('*'):
            if item.is_file() and item.suffix != '.py':
                skipped_files += 1


        defs_xml = "".join([
            f"<definition><file>{ET.escape(d['file'])}</file><name>{ET.escape(d['name'])}</name><type>{ET.escape(d['type'])}</type></definition>"
            for d in definitions
        ])

        message = f"Found {len(definitions)} definitions in {processed_files} Python file(s)."
        if skipped_files > 0:
             message += f" Skipped {skipped_files} non-Python files."
        if def_count >= max_defs:
            message += f" Stopped at maximum limit ({max_defs})."
        message += " Note: This tool currently only parses Python files. Use 'execute_command' with external tools (e.g., ctags) for other languages."


        return f"<tool_result tool_name=\"list_code_definition_names\"><status>success</status><message>{ET.escape(message)}</message><definitions>{defs_xml}</definitions></tool_result>"

    except (ValueError, IOError) as e:
        return f"<tool_result tool_name=\"list_code_definition_names\"><status>error</status><message>{ET.escape(str(e))}</message></tool_result>"
    except Exception as e:
        return f"<tool_result tool_name=\"list_code_definition_names\"><status>error</status><message>Unexpected error listing definitions: {ET.escape(str(e))}</message></tool_result>"


# --- Tool Execution Engine (NTEE) ---
# Maps tool names to their implementation functions
TOOL_REGISTRY = {
    "read_file": _tool_read_file,
    "write_to_file": _tool_write_to_file,
    "execute_command": _tool_execute_command,
    "replace_in_file": _tool_replace_in_file,
    "search_files": _tool_search_files,
    "list_files": _tool_list_files,
    "list_code_definition_names": _tool_list_code_definition_names,
}

def parse_tool_call(response_text: str) -> Optional[Tuple[str, Dict[str, str]]]:
    """
    Parses the LLM response text to find the *first* XML tool call.
    Returns (tool_name, parameters_dict) or None if no valid tool call is found.
    Handles special tools 'ask_followup_question' and 'attempt_completion'.
    """
    try:
        # Find the first opening tag that matches a known tool or special command
        first_tool_match = None
        first_tool_pos = -1
        known_tools = list(TOOL_REGISTRY.keys()) + ["ask_followup_question", "attempt_completion"]

        for tool_name in known_tools:
            open_tag = f"<{tool_name}>"
            pos = response_text.find(open_tag)
            if pos != -1 and (first_tool_pos == -1 or pos < first_tool_pos):
                first_tool_pos = pos
                first_tool_match = tool_name

        if not first_tool_match:
            return None # No known tool call found

        # Extract the content within the first matched tool's tags
        open_tag = f"<{first_tool_match}>"
        close_tag = f"</{first_tool_match}>"
        start_index = response_text.find(open_tag)
        # Find the *correct* closing tag, handling potential nesting issues simply
        end_index = response_text.find(close_tag, start_index + len(open_tag))

        if start_index == -1 or end_index == -1:
            console.print(f"[yellow]⚠[/yellow] Malformed XML for tool '{first_tool_match}'. Tags not found or incorrect.", style="yellow")
            return None

        tool_content = response_text[start_index + len(open_tag):end_index].strip()

        # Parse parameters within the tool content using simplified XML parsing
        params = {}
        try:
            # Use regex to find <tag>value</tag> pairs within the tool_content
            param_pattern = re.compile(r"<(\w+)>(.*?)</\1>", re.DOTALL)
            for match in param_pattern.finditer(tool_content):
                tag_name = match.group(1)
                tag_value = match.group(2).strip() # Keep internal whitespace, strip ends
                # Basic unescaping for XML entities the LLM might generate
                tag_value = tag_value.replace("<", "<").replace(">", ">").replace("&", "&").replace('"', '"').replace("'", "'")
                params[tag_name] = tag_value

            # Handle special cases where the main content might not be tagged correctly
            if not params:
                 if first_tool_match == "ask_followup_question" and tool_content:
                     params["question"] = tool_content # Assume raw content is the question
                 elif first_tool_match == "attempt_completion" and tool_content:
                     params["result"] = tool_content # Assume raw content is the result

            # If still no params for tools that require them, it's an error
            if not params and first_tool_match in TOOL_REGISTRY:
                 # Check if content looks like parameters but failed regex
                 if '<' in tool_content and '>' in tool_content:
                      console.print(f"[yellow]⚠[/yellow] Could not parse parameters for '{first_tool_match}' using regex. Content: {tool_content}", style="yellow")
                 else: # Content might be missing parameters entirely
                      console.print(f"[yellow]⚠[/yellow] No parameters found for tool '{first_tool_match}'.", style="yellow")
                 # Allow proceeding if maybe the tool can handle missing params, but log warning
                 # return None # Stricter: fail if params expected but not found

        except Exception as e:
            console.print(f"[red]✗ Error:[/red] Error parsing parameters for '{first_tool_match}': {e}", style="bold red")
            return None # Indicate parsing failure

        return first_tool_match, params

    except Exception as e:
        console.print(f"[red]✗ Error:[/red] Unexpected error during tool parsing: {e}", style="bold red")
        return None


def execute_tool(tool_name: str, params: Dict[str, str]) -> str:
    """
    Executes the specified tool with the given parameters.
    Returns the XML result string to be sent back to the LLM.
    """
    console.print(f"\n[bold blue]Executing Tool:[/bold blue] {tool_name}")
    if tool_name in TOOL_REGISTRY:
        tool_function = TOOL_REGISTRY[tool_name]
        try:
            # Basic parameter validation (check if required params are present) could be added here
            result = tool_function(params)
            console.print(f"[bold green]Tool Result:[/bold green]\n{result}")
            return result
        except Exception as e:
            console.print(f"[red]✗ Error:[/red] Failed to execute tool '{tool_name}': {e}", style="bold red")
            # Ensure the error message is XML-escaped for safety
            escaped_error = ET.escape(f"Internal error during tool execution: {str(e)}")
            return f"<tool_result tool_name=\"{tool_name}\"><status>error</status><message>{escaped_error}</message></tool_result>"
    else:
        # This case should ideally not be reached if parse_tool_call works correctly
        console.print(f"[red]✗ Error:[/red] Unknown tool requested for execution: '{tool_name}'", style="bold red")
        return f"<tool_result tool_name=\"{tool_name}\"><status>error</status><message>Unknown tool requested.</message></tool_result>"

# --- Core Interaction Logic (NATS Simulation) ---
# This loop simulates the autonomous task sequencing.
# A true NATS would involve more complex planning, state management, and error recovery.
MAX_TURNS = 10 # Safety limit for conversation length

def run_conversation_turn(history: List[Dict[str, str]]) -> Tuple[str, Optional[str], Optional[Dict[str, str]], bool]:
    """
    Runs a single turn of the conversation: calls LLM, parses response.
    Returns: (raw_assistant_response, tool_name, tool_params, is_completion)
    """
    try:
        console.print(f"\n[yellow]Calling LLM (model: {model_name})...[/yellow]")
        # Use a copy of history to avoid modifying the state directly here
        current_history = history[:]
        stream = client.chat.completions.create(
            model=model_name,
            messages=current_history,
            # response_format={"type": "json_object"}, # REMOVED - Expecting text/XML now
            max_tokens=4096, # Increased max_tokens
            stream=True,
            temperature=0.1, # Lower temperature for more deterministic tool use
            # stop=["</tool_result>"] # Optional: Stop generation after a tool result tag is closed
        )

        full_response = ""
        console.print("\n[bold blue]Assistant:[/bold blue] ", end="")
        for chunk in stream:
            content_chunk = chunk.choices[0].delta.content
            if content_chunk:
                full_response += content_chunk
                console.print(content_chunk, end="", flush=True)
        console.print() # Newline after streaming

        if not full_response:
             # Handle empty response from LLM
             console.print("[yellow]⚠[/yellow] LLM returned an empty response.", style="yellow")
             # Decide how to proceed: treat as error, ask user, or retry?
             # For now, treat as a completion with an error message.
             return "Error: LLM returned an empty response.", None, None, True


        # --- NTEE: Parse for Tool Call ---
        # We parse the *full* response after streaming is complete
        tool_info = parse_tool_call(full_response)

        # Add the raw assistant response to history *after* parsing it
        # This ensures the history reflects what was actually processed
        history.append({"role": "assistant", "content": full_response})


        if tool_info:
            tool_name, tool_params = tool_info
            if tool_name == "attempt_completion":
                # Check the critical rule: Has the previous tool use been confirmed?
                # This requires more sophisticated state tracking than currently implemented.
                # For now, we proceed but log a warning.
                console.print("[bold yellow]Warning:[/bold yellow] Proceeding with 'attempt_completion'. Ensure previous tool results were successful (manual check required).", style="yellow")
                console.print("[bold green]Completion Attempted.[/bold green]")
                return full_response, tool_name, tool_params, True # Signal completion
            elif tool_name == "ask_followup_question":
                 console.print("[bold yellow]Follow-up Question Asked.[/bold yellow]")
                 # Ensure question parameter exists
                 if "question" not in tool_params:
                      console.print("[red]✗ Error:[/red] 'ask_followup_question' called without <question> parameter.", style="bold red")
                      return full_response, None, None, True # Treat as error completion
                 return full_response, tool_name, tool_params, True # Signal completion (needs user input)
            else:
                # It's a regular tool call, return it for execution
                return full_response, tool_name, tool_params, False
        else:
            # No valid tool call found in the response.
            # Treat this as a final textual response from the assistant.
            console.print("[yellow]ℹ[/yellow] No tool call detected. Treating as final response.", style="yellow")
            return full_response, None, None, True # Treat as completion

    except APIError as e:
        error_msg = f"OpenAI API Error: {e}"
        console.print(f"\n[red]✗ Error:[/red] {error_msg}", style="bold red")
        # Add error to history? Maybe not, let the user see it and decide.
        # history.append({"role": "assistant", "content": f"API Error: {e}"})
        return f"API Error: {e}", None, None, True # End turn on API error
    except Exception as e:
        error_msg = f"Error during LLM call or processing: {e}"
        console.print(f"\n[red]✗ Error:[/red] {error_msg}", style="bold red")
        # history.append({"role": "assistant", "content": f"Internal Error: {e}"})
        return f"Internal Error: {e}", None, None, True # End turn on other errors


# --- Gradio Interface ---
# Use state to maintain conversation history across interactions
def chat_with_nexa(message: str, history_state: List[Dict[str, str]]):
    """Handles the multi-turn conversation flow within Gradio."""

    # Initialize history if it's the first turn or state is invalid
    if not isinstance(history_state, list) or not history_state:
        history_state = [{"role": "system", "content": system_prompt}]
        console.print("[yellow]ℹ[/yellow] Initializing new conversation history.")
    elif not history_state or history_state[0].get("role") != "system": # Check if empty or first element is not system prompt
         console.print("[yellow]⚠[/yellow] Invalid or empty history state detected. Re-initializing.", style="yellow")
         history_state = [{"role": "system", "content": system_prompt}]


    # Add user message to the state
    history_state.append({"role": "user", "content": message})
    console.print(f"\n[bold green]User:[/bold green] {message}")

    # Prepare the output log string
    output_log = f"User: {message}\n\n"

    # --- Autonomous Loop (NATS Simulation) ---
    for turn in range(MAX_TURNS):
        console.print(f"\n--- Turn {turn + 1}/{MAX_TURNS} ---")

        # Pass the current history state to the turn function
        raw_assistant_response, tool_name, tool_params, is_completion = run_conversation_turn(history_state)

        # Append assistant's raw response to the log
        output_log += f"Assistant:\n```text\n{raw_assistant_response}\n```\n\n"

        if is_completion:
            if tool_name == "attempt_completion":
                final_result = tool_params.get("result", "Task completed (no result message provided).")
                output_log += f"**Nexa (Completion):**\n{final_result}\n\n"
                # Optionally execute demonstration command
                demo_command = tool_params.get("command")
                if demo_command:
                    output_log += f"(Attempting to demonstrate with: `{demo_command}`)\n"
                    try:
                         # Execute demo command with NO approval prompt (use carefully!)
                         code, out, err = _execute_command_impl(demo_command, requires_approval=False)
                         output_log += f"Demonstration command exit code: {code}\n"
                         if out: output_log += f"stdout:\n```\n{out}\n```\n"
                         if err: output_log += f"stderr:\n```\n{err}\n```\n"
                    except Exception as e:
                         output_log += f"Demonstration command failed to execute: {e}\n"

            elif tool_name == "ask_followup_question":
                question = tool_params.get("question", "I need more information (question text missing).")
                output_log += f"**Nexa (Needs Input):**\n{question}\n"
            else:
                 # Simple text response or error completion
                 output_log += f"**Nexa (Final Response):**\n(No further actions taken)\n"
            break # Exit loop on any completion type

        if tool_name and tool_params:
            # --- NTEE: Execute Tool ---
            tool_result_xml = execute_tool(tool_name, tool_params)
            output_log += f"System (Tool Execution: {tool_name}):\n```xml\n{tool_result_xml}\n```\n\n"
            # Add tool result to history for the next LLM call
            # Use 'user' role for tool results as per some API guidelines, or 'system'
            history_state.append({"role": "user", "content": tool_result_xml})
        else:
            # This case indicates an error state: not completion, but no tool call either.
            output_log += "**Nexa (Error):** Assistant response did not result in an action or completion.\n"
            console.print("[red]✗ Error:[/red] Inconsistent state: No tool found, but not marked as completion.", style="bold red")
            break # Exit loop on error state

    else: # Loop finished without breaking (MAX_TURNS reached)
        output_log += f"**Nexa (Stopped):** Maximum conversation turns ({MAX_TURNS}) reached. Please refine your request or start a new conversation.\n"
        console.print(f"[yellow]⚠[/yellow] Maximum turns ({MAX_TURNS}) reached.", style="yellow")


    # Return the full log and the updated history state for Gradio
    return output_log, history_state


# Create Gradio Interface with State
chatbot_output = gr.Textbox(label="Conversation Log", lines=25, interactive=False, elem_id="conversation-log")

interface = gr.Interface(
    fn=chat_with_nexa,
    inputs=[
        gr.Textbox(label="Your Request", placeholder="Enter your coding request here...", lines=3),
        gr.State([]) # Initialize empty state for history
    ],
    outputs=[
        chatbot_output,
        gr.State() # Output the updated state
    ],
    title="Nexa - Autonomous AI Coding Assistant (Concept v2.1)",
    description=(
        "Welcome to Nexa! Enter your request. Nexa will use tools iteratively (up to 10 turns) to try and fulfill it. "
        f"\nWorking Directory: `{cwd.as_posix()}`"
        "\n**Warning:** `execute_command` requires confirmation for risky operations. Use with extreme caution."
        "\n**Note:** Complex examples (like building full apps) are aspirational and may fail due to the current system's limitations in planning and error handling. Simpler, tool-focused requests are more likely to succeed."
        "\n(`list_code_definition_names` currently only supports Python)."

    ),
    allow_flagging="never",
    examples=[ # Examples ranging from simple to complex/aspirational
        # Simple Tool Demos
        ["Create a python file named 'hello.py' that prints 'Hello, World!'"],
        ["Read the file 'hello.py'"],
        ["List all python files in the current directory recursively"],
        ["Search for the word 'import' in all '.py' files in the 'src' directory"],
        ["Run the command 'python hello.py'"],
        ["Replace 'World' with 'Nexa' in 'hello.py' using a SEARCH/REPLACE block"],
        # More Complex / Aspirational Examples (May Fail)
        ["Create a simple Flask web server in 'app.py' that serves 'index.html'"],
        ["Create a basic HTML file 'index.html' with a title 'My App' and a heading 'Welcome'"],
        ["Install the 'qrcode' library using pip"],
        ["Create a Python script 'qr_generator.py' that takes text input and generates a QR code image file named 'output.png' using the 'qrcode' library."],
        ["Build a simple command-line travel planner in Python: ask for destination, dates, and budget, then save to 'plan.txt'."],
        ["Generate a basic structure for a blog content generator app using Flask (app.py, templates/index.html, requirements.txt)."]
    ],
    css="#conversation-log { font-family: monospace; }" # Use monospace font for log
)

# --- Main Execution ---
if __name__ == "__main__":
    console.print("[bold green]Launching Nexa Gradio Interface...[/bold green]")
    console.print(f"Working Directory: [cyan]{cwd}[/cyan]")
    console.print("[bold yellow]Warning:[/bold yellow] The `execute_command` tool can run arbitrary code. Ensure you understand the risks.", style="yellow")
    interface.launch()
