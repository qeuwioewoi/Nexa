#!/usr/bin/env python3

import os
import sys
import json
from pathlib import Path
from typing import List, Optional
from openai import OpenAI
from pydantic import BaseModel
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
import gradio as gr  # Replace Chainlit with Gradio

# Initialize Rich console
console = Console()

# --------------------------------------------------------------------------------
# 1. Load configuration from coder.config
# --------------------------------------------------------------------------------
def load_config(config_file: str = "coder.config") -> dict:
    """Load configuration from a JSON file."""
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        console.print(f"[red]✗[/red] Configuration file '{config_file}' not found.", style="red")
        sys.exit(1)
    except json.JSONDecodeError:
        console.print(f"[red]✗[/red] Invalid JSON in configuration file '{config_file}'.", style="red")
        sys.exit(1)

config = load_config()

# --------------------------------------------------------------------------------
# 2. Configure OpenAI client and load environment variables
# --------------------------------------------------------------------------------
load_dotenv()  # Load environment variables from .env file
client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),  # Use OpenRouter API key
    base_url=config.get("api_base_url", "https://openrouter.ai/api/v1")  # OpenRouter API base URL
)

# Get the model name from the config
model_name = config.get("model_name", "deepseek-chat")

# --------------------------------------------------------------------------------
# 3. Define our schema using Pydantic for type safety
# --------------------------------------------------------------------------------
class FileToCreate(BaseModel):
    path: str
    content: str

class FileToEdit(BaseModel):
    path: str
    original_snippet: str
    new_snippet: str

class AssistantResponse(BaseModel):
    assistant_reply: str
    files_to_create: Optional[List[FileToCreate]] = None
    files_to_edit: Optional[List[FileToEdit]] = None

# --------------------------------------------------------------------------------
# 4. System prompt
# --------------------------------------------------------------------------------
system_PROMPT = config.get("system_PROMPT", "")

# --------------------------------------------------------------------------------
# 5. Helper functions
# --------------------------------------------------------------------------------
def read_local_file(file_path: str) -> str:
    """Return the text content of a local file."""
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()

def create_file(path: str, content: str):
    """Create (or overwrite) a file at 'path' with the given 'content'."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    console.print(f"[green]✓[/green] Created/updated file at '[cyan]{file_path}[/cyan]'")

def show_diff_table(files_to_edit: List[FileToEdit]) -> None:
    """Show a table of proposed edits."""
    if not files_to_edit:
        return
    table = Table(title="Proposed Edits", show_header=True, header_style="bold magenta", show_lines=True)
    table.add_column("File Path", style="cyan")
    table.add_column("Original", style="red")
    table.add_column("New", style="green")
    for edit in files_to_edit:
        table.add_row(edit.path, edit.original_snippet, edit.new_snippet)
    console.print(table)

def apply_diff_edit(path: str, original_snippet: str, new_snippet: str):
    """Apply a diff edit to a file."""
    try:
        content = read_local_file(path)
        if original_snippet in content:
            updated_content = content.replace(original_snippet, new_snippet, 1)
            create_file(path, updated_content)
            console.print(f"[green]✓[/green] Applied diff edit to '[cyan]{path}[/cyan]'")
        else:
            console.print(f"[yellow]⚠[/yellow] Original snippet not found in '[cyan]{path}[/cyan]'. No changes made.", style="yellow")
    except FileNotFoundError:
        console.print(f"[red]✗[/red] File not found for diff editing: '[cyan]{path}[/cyan]'", style="red")

def guess_files_in_message(user_message: str) -> List[str]:
    """
    Attempt to guess which files the user might be referencing.
    Returns normalized absolute paths.
    """
    recognized_extensions = [".css", ".html", ".js", ".py", ".json", ".md"]
    potential_paths = []
    for word in user_message.split():
        if any(ext in word for ext in recognized_extensions) or "/" in word:
            path = word.strip("',\"")
            try:
                normalized_path = normalize_path(path)
                potential_paths.append(normalized_path)
            except (OSError, ValueError):
                continue
    return potential_paths

def normalize_path(path_str: str) -> str:
    """Return a canonical, absolute version of the path."""
    return str(Path(path_str).resolve())

def ensure_file_in_context(file_path: str) -> bool:
    """
    Ensures the file content is in the conversation context.
    Returns True if successful, False if file not found.
    """
    try:
        normalized_path = normalize_path(file_path)
        content = read_local_file(normalized_path)
        file_marker = f"Content of file '{normalized_path}'"
        # Add to conversation if we haven't already
        if not any(file_marker in msg["content"] for msg in conversation_history):
            conversation_history.append({
                "role": "system",
                "content": f"{file_marker}:\n\n{content}"
            })
        return True
    except OSError:
        console.print(f"[red]✗[/red] Could not read file '[cyan]{file_path}[/cyan]' for editing context", style="red")
        return False

# --------------------------------------------------------------------------------
# 6. Conversation state
# --------------------------------------------------------------------------------
conversation_history = [
    {"role": "system", "content": system_PROMPT}
]

# --------------------------------------------------------------------------------
# 7. OpenAI API interaction with streaming
# --------------------------------------------------------------------------------
def stream_openai_response(user_message: str):
    """
    Streams the OpenRouter chat completion response and handles structured output.
    Returns the final AssistantResponse.
    """
    # Attempt to guess which file(s) user references
    potential_paths = guess_files_in_message(user_message)
    
    valid_files = {}

    # Try to read all potential files before the API call
    for path in potential_paths:
        try:
            content = read_local_file(path)
            valid_files[path] = content  # path is already normalized
            file_marker = f"Content of file '{path}'"
            # Add to conversation if we haven't already
            if not any(file_marker in msg["content"] for msg in conversation_history):
                conversation_history.append({
                    "role": "system",
                    "content": f"{file_marker}:\n\n{content}"
                })
        except OSError:
            error_msg = f"Cannot proceed: File '{path}' does not exist or is not accessible"
            console.print(f"[red]✗[/red] {error_msg}", style="red")
            continue

    # Now proceed with the API call
    conversation_history.append({"role": "user", "content": user_message})

    try:
        stream = client.chat.completions.create(
            model=model_name,  # Use the model name from the config
            messages=conversation_history,
            response_format={"type": "json_object"},
            max_completion_tokens=8000,
            stream=True
        )

        console.print("\nAssistant> ", style="bold blue", end="")
        full_content = ""

        for chunk in stream:
            if chunk.choices[0].delta.content:
                content_chunk = chunk.choices[0].delta.content
                full_content += content_chunk
                console.print(content_chunk, end="")

        console.print()

        try:
            parsed_response = json.loads(full_content)
            
            # [NEW] Ensure assistant_reply is present
            if "assistant_reply" not in parsed_response:
                parsed_response["assistant_reply"] = ""

            # If assistant tries to edit files not in valid_files, remove them
            if "files_to_edit" in parsed_response and parsed_response["files_to_edit"]:
                new_files_to_edit = []
                for edit in parsed_response["files_to_edit"]:
                    try:
                        edit_abs_path = normalize_path(edit["path"])
                        # If we have the file in context or can read it now
                        if edit_abs_path in valid_files or ensure_file_in_context(edit_abs_path):
                            edit["path"] = edit_abs_path  # Use normalized path
                            new_files_to_edit.append(edit)
                    except (OSError, ValueError):
                        console.print(f"[yellow]⚠[/yellow] Skipping invalid path: '{edit['path']}'", style="yellow")
                        continue
                parsed_response["files_to_edit"] = new_files_to_edit

            response_obj = AssistantResponse(**parsed_response)

            # Save the assistant's textual reply to conversation
            conversation_history.append({
                "role": "assistant",
                "content": response_obj.assistant_reply
            })

            return response_obj

        except json.JSONDecodeError:
            error_msg = "Failed to parse JSON response from assistant"
            console.print(f"[red]✗[/red] {error_msg}", style="red")
            return AssistantResponse(
                assistant_reply=error_msg,
                files_to_create=[]
            )

    except Exception as e:
        error_msg = f"OpenRouter API error: {str(e)}"
        console.print(f"\n[red]✗[/red] {error_msg}", style="red")
        return AssistantResponse(
            assistant_reply=error_msg,
            files_to_create=[]
        )

# --------------------------------------------------------------------------------
# 8. Gradio Interface
# --------------------------------------------------------------------------------
def chat_with_nexa(message):
    """Handle incoming messages."""
    # Stream the assistant's response
    response_data = stream_openai_response(message)

    # Handle file creation
    if response_data.files_to_create:
        for file_info in response_data.files_to_create:
            create_file(file_info.path, file_info.content)

    # Handle file edits
    if response_data.files_to_edit:
        # Show the diff table (for Gradio, we'll return it as a string)
        table_content = "Proposed Edits:\n\n"
        for edit in response_data.files_to_edit:
            table_content += f"File: {edit.path}\nOriginal: {edit.original_snippet}\nNew: {edit.new_snippet}\n\n"
        return f"{response_data.assistant_reply}\n\n{table_content}"
    
    return response_data.assistant_reply

# Create a Gradio interface
interface = gr.Interface(
    fn=chat_with_nexa,
    inputs="text",
    outputs="text",
    title="Nexa - AI Coding Assistant",
    description="Welcome to Nexa! How can I assist you today?"
)

# --------------------------------------------------------------------------------
# 9. Main function
# --------------------------------------------------------------------------------
if __name__ == "__main__":
    # Launch the Gradio app
    interface.launch()