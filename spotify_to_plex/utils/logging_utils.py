"""Utility functions for enhanced logging and output formatting."""

import os
import sys
import time
import threading
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union, Callable, TypeVar

import rtoml
from loguru import logger

# Type variable for generic return types
T = TypeVar('T')

# Terminal-safe symbols that render consistently across platforms
class Symbols:
    """Unicode symbols chosen for broader terminal compatibility."""
    # General Status
    INFO = "ℹ"
    DEBUG = "»"
    WARNING = "▲"
    ERROR = "✖"
    SUCCESS = "✔"

    # Media / Specific Apps (Using safer symbols)
    MUSIC = "♪"
    PLAYLIST = "♫"
    USER = "●"
    USERS = "◎"
    SPOTIFY = "♫"
    PLEX = "▶"
    TRACK = "•"
    TRACKS = "::"

    # Actions / Processes
    PROCESSING = "⏳"
    SEARCH = "*"
    TIME = "⊙"
    START = "▶"
    FINISH = "✔"
    CACHE = "◇"
    CONFIG = "☰"
    LIST = "≡"
    SYNC = "↻"
    DATE = "¤"
    ARROW = "➤"
    BATCH = "▣"
    THREAD = "~~"
    PROGRESS = "⏳"


# Console output lock to prevent race conditions
console_lock = threading.RLock()


def get_version() -> str:
    """Get the current version from multiple sources.

    Checks in this order:
    1. Git tag (if in a git repository)
    2. pyproject.toml file
    3. VERSION file in various locations
    4. Hardcoded fallback

    Returns:
        str: The version string
    """
    # Try to get the version from Git
    try:
        version = subprocess.check_output(
            ["git", "describe", "--tags", "--abbrev=0"],
            stderr=subprocess.DEVNULL
        ).decode("utf-8").strip()

        if version:
            return version
    except (subprocess.SubprocessError, FileNotFoundError):
        logger.debug("Could not get version from git")

    # Try to read from pyproject.toml
    try:
        # Look for pyproject.toml in common locations
        possible_toml_paths = [
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "pyproject.toml"),
            "pyproject.toml",
            os.path.join(os.getcwd(), "pyproject.toml"),
        ]

        for toml_path in possible_toml_paths:
            if os.path.exists(toml_path):
                try:
                    with open(toml_path, 'r') as f:
                        config = rtoml.load(f)
                        if config and 'tool' in config and 'poetry' in config['tool']:
                            version = config['tool']['poetry'].get('version')
                            if version:
                                logger.debug(f"Retrieved version {version} from pyproject.toml")
                                return version
                except Exception as e:
                    logger.debug(f"Error reading version from {toml_path}: {e}")
    except Exception as e:
        logger.debug(f"Error processing pyproject.toml: {e}")

    # Look for VERSION file in various locations
    possible_paths = [
        # Path relative to the logging_utils.py file
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "VERSION"),
        # Path if run from the project root
        "VERSION",
        # Path from the current working directory
        os.path.join(os.getcwd(), "VERSION"),
    ]

    for path in possible_paths:
        try:
            if os.path.exists(path):
                with open(path, "r") as f:
                    version = f.read().strip()
                    if version:
                        logger.debug(f"Retrieved version {version} from {path}")
                        return version
        except (IOError, OSError) as e:
            logger.debug(f"Error reading version from {path}: {e}")

    # Fallback to default
    logger.debug("Using fallback version")
    return "2.1.0"  # Hardcode latest version as fallback


def perform_task(func: Callable[..., T], message: str, *args: Any, **kwargs: Any) -> T:
    """Execute a function with a status message and proper error handling.

    Args:
        func: The function to execute
        message: A description of the task
        *args: Arguments to pass to the function
        **kwargs: Keyword arguments to pass to the function

    Returns:
        The result of the function call

    Raises:
        Exception: If the function call fails
    """
    log_info(f"Task: {message}", Symbols.PROCESSING)
    try:
        result = func(*args, **kwargs)
        log_debug(f"Task completed: {message}", Symbols.SUCCESS)
        return result
    except Exception as e:
        log_error(f"Task failed: {message} - {str(e)}")
        raise  # Re-raise the exception after logging


class ProgressBar:
    """Text-based progress bar with percentage indicator and spinner."""

    def __init__(self, total: int, prefix: str = "", suffix: str = "", length: int = 30) -> None:
        """Initialize a progress bar.

        Args:
            total: Total number of items to process
            prefix: Text to display before the bar
            suffix: Text to display after the bar
            length: Character length of the bar
        """
        self.total = max(1, total)  # Avoid division by zero
        self.prefix = prefix
        self.suffix = suffix
        self.length = length
        self.current = 0
        self.start_time = time.time()
        self._lock = threading.RLock()
        self._last_line_length = 0
        self._line_active = False
        self._spinner_idx = 0
        self._spinner_chars = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']

    def update(self, current: Optional[int] = None) -> None:
        """Update the progress bar with a spinner.

        Args:
            current: Current progress value (if None, increments by 1)
        """
        with self._lock:
            if current is not None:
                self.current = current
            else:
                self.current += 1

            # Update spinner index
            self._spinner_idx = (self._spinner_idx + 1) % len(self._spinner_chars)
            spinner_char = self._spinner_chars[self._spinner_idx]

            self.current = min(self.current, self.total)
            percent = 100 * (self.current / self.total)

            # Calculate elapsed time and ETA
            elapsed = time.time() - self.start_time
            eta = "N/A"
            if self.current > 0:
                eta_seconds = elapsed * (self.total - self.current) / self.current
                if eta_seconds < 60:
                    eta = f"{eta_seconds:.0f}s"
                elif eta_seconds < 3600:
                    eta = f"{eta_seconds/60:.1f}m"
                else:
                    eta = f"{eta_seconds/3600:.1f}h"

            # Create the progress bar
            filled_length = int(self.length * self.current // self.total)
            bar = '#' * filled_length + '-' * (self.length - filled_length)

            # Print the progress bar with better visual separation
            with console_lock:
                # Always detect if we need a newline by checking cursor position
                # This ensures we don't overlap with other output that may have
                # been printed between progress bar updates
                try:
                    # We can't directly detect cursor position, so use a safer approach
                    # If our line_active flag is False, it means other output likely occurred
                    if not self._line_active:
                        sys.stdout.write("\n")
                        sys.stdout.flush()
                except Exception:
                    # Always add a newline if we can't determine state
                    sys.stdout.write("\n")
                    sys.stdout.flush()

                # Calculate the line content - make it more compact
                line = f"{spinner_char} {self.prefix} [{bar}] {percent:.1f}% ({self.current}/{self.total}) {self.suffix}"

                # Clear the previous line completely
                sys.stdout.write("\r" + " " * self._last_line_length + "\r")
                sys.stdout.write(line)
                sys.stdout.flush()

                # Store the new line length
                self._last_line_length = len(line)
                # Mark that we have an active progress line
                self._line_active = True

    def clear_line(self) -> None:
        """Clear the current progress bar line and reset to start of line."""
        with self._lock:
            if self._line_active:
                with console_lock:
                    sys.stdout.write("\r" + " " * self._last_line_length + "\r")
                    sys.stdout.flush()
                    self._line_active = False

    def ensure_newline(self) -> None:
        """Ensure that the next output starts on a new line."""
        with self._lock:
            if self._line_active:
                with console_lock:
                    # More forcefully ensure we move to a new line
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    self._line_active = False

    def finish(self) -> None:
        """Mark the progress bar as complete with timing information."""
        with self._lock:
            self.update(self.total)
            elapsed = time.time() - self.start_time
            time_str = f"{elapsed:.1f}s" if elapsed < 60 else f"{elapsed/60:.1f}m"
            with console_lock:
                sys.stdout.write(f" (completed in {time_str})\n\n")  # Add double newline for consistent spacing
                sys.stdout.flush()
                self._line_active = False


def setup_logging(log_level: str = "INFO", log_dir: str = "logs") -> None:
    """Set up unified logging with file output only.

    Args:
        log_level: Minimum level for console log output
        log_dir: Directory to store log files
    """
    # Create log directory if it doesn't exist
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError as e:
        print(f"Warning: Could not create log directory {log_dir}: {e}")
        log_dir = "."  # Fall back to current directory

    # Define format for file logging
    file_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "{message}"
    )

    # Remove default handlers
    logger.remove()

    # Add file handler for detailed logging
    try:
        logger.add(
            f"{log_dir}/spotify_to_plex_{{time:YYYY-MM-DD}}.log",
            format=file_format,
            level="DEBUG",  # Always use DEBUG for file
            rotation="12:00",
            retention="7 days",
            compression="zip",
            backtrace=True,
            diagnose=True,
            enqueue=True,  # Use queue to avoid conflicts
        )
    except Exception as e:
        print(f"Warning: Could not set up file logger: {e}")


def draw_box(text: str, padding: int = 2, extra_width: int = 0) -> Tuple[str, str, str]:
    """Draw a box around text with proper alignment.

    Args:
        text: The text to put in the box
        padding: Horizontal padding inside the box
        extra_width: Additional width to add to the box

    Returns:
        Tuple of (top_border, content_line, bottom_border)
    """
    text_width = len(text)
    box_width = text_width + (padding * 2) + extra_width

    top_border = f"┏{'━' * box_width}┓"
    content_line = f"┃{' ' * padding}{text}{' ' * (padding + extra_width)}┃"
    bottom_border = f"┗{'━' * box_width}┛"

    return (top_border, content_line, bottom_border)


# Global progress bar reference for coordination between logging functions
_current_progress_bar: Optional[ProgressBar] = None

def set_active_progress_bar(bar: Optional[ProgressBar]) -> None:
    """Set the currently active progress bar.

    Args:
        bar: The ProgressBar instance to set as active
    """
    global _current_progress_bar
    _current_progress_bar = bar

def ensure_newline() -> None:
    """Ensure that the next output starts on a new line.

    This function makes sure that we're starting output on a new line,
    which helps prevent messages from overlapping with progress bars.
    """
    global _current_progress_bar
    with console_lock:
        # If there's an active progress bar, use its method
        if _current_progress_bar is not None and _current_progress_bar._line_active:
            _current_progress_bar.ensure_newline()
        else:
            # Even without an active progress bar, check if we might need a newline
            # by writing a CR+LF sequence to ensure clean output
            sys.stdout.write("\r\n")
            sys.stdout.flush()


def log(level: str, message: str, symbol: Optional[str] = None,
        console_only: bool = False, file_only: bool = False, **context: Any) -> None:
    """Log a message with the appropriate level and symbol.

    Args:
        level: Log level (info, debug, warning, error, success)
        message: The message to log
        symbol: Override the default symbol for this log level
        console_only: Only output to console, not log file
        file_only: Only output to log file, not console
        **context: Additional context to include in the log
    """
    # Always ensure we're on a new line before logging anything
    ensure_newline()

    if symbol is None:
        symbol = getattr(Symbols, level.upper(), Symbols.INFO)

    # Format message with appropriate symbol
    formatted_msg = f"{symbol} {message}"

    # Determine color based on level
    color_map = {
        "info": "\033[0m",      # Reset/default
        "debug": "\033[36m",    # Cyan
        "warning": "\033[33m",  # Yellow
        "error": "\033[31m",    # Red
        "success": "\033[32m",  # Green
    }
    color = color_map.get(level.lower(), "\033[0m")
    reset = "\033[0m"

    # Control where the message goes - AVOID DUPLICATION
    if file_only:
        # Only log to file
        getattr(logger, level.lower())(formatted_msg, **context)
    elif console_only:
        # Only print to console with color
        with console_lock:
            print(f"{color}{formatted_msg}{reset}")
            sys.stdout.flush()
    else:
        # Log to file
        getattr(logger, level.lower())(formatted_msg, **context)
        # AND print to console with color (without timestamp duplication)
        with console_lock:
            print(f"{color}{formatted_msg}{reset}")
            sys.stdout.flush()


def log_info(message: str, symbol: Optional[str] = None,
             console_only: bool = False, **context: Any) -> None:
    """Log an info message.

    Args:
        message: The message to log
        symbol: Override the default symbol
        console_only: Only output to console, not log file
        **context: Additional context to include in the log
    """
    # Force ensure newline for track-related messages
    if symbol in (Symbols.TRACK, Symbols.TRACKS, Symbols.MUSIC):
        ensure_newline()
    log("INFO", message, symbol or Symbols.INFO, console_only, **context)


def log_debug(message: str, symbol: Optional[str] = None,
              console_only: bool = False, file_only: bool = True, **context: Any) -> None:
    """Log a debug message (file-only by default).

    Args:
        message: The message to log
        symbol: Override the default symbol
        console_only: Only output to console, not log file
        file_only: Only output to log file, not console
        **context: Additional context to include in the log
    """
    log("DEBUG", message, symbol or Symbols.DEBUG, console_only, file_only, **context)


def log_warning(message: str, symbol: Optional[str] = None,
                console_only: bool = False, **context: Any) -> None:
    """Log a warning message.

    Args:
        message: The message to log
        symbol: Override the default symbol
        console_only: Only output to console, not log file
        **context: Additional context to include in the log
    """
    log("WARNING", message, symbol or Symbols.WARNING, console_only, **context)


def log_error(message: str, symbol: Optional[str] = None,
              console_only: bool = False, **context: Any) -> None:
    """Log an error message.

    Args:
        message: The message to log
        symbol: Override the default symbol
        console_only: Only output to console, not log file
        **context: Additional context to include in the log
    """
    log("ERROR", message, symbol or Symbols.ERROR, console_only, **context)


def log_success(message: str, symbol: Optional[str] = None,
                console_only: bool = False, **context: Any) -> None:
    """Log a success message.

    Args:
        message: The message to log
        symbol: Override the default symbol
        console_only: Only output to console, not log file
        **context: Additional context to include in the log
    """
    log("SUCCESS", message, symbol or Symbols.SUCCESS, console_only, **context)


def log_header(message: str) -> None:
    """Log a section header with distinct formatting.

    Args:
        message: The header text (will be converted to uppercase)
    """
    # Convert to uppercase
    header = message.upper()

    # Ensure we're starting with plenty of space
    with console_lock:
        # Create spacious formatting with proper alignment
        print("\n\n")
        top, content, bottom = draw_box(header, padding=4, extra_width=2)
        print(top)
        print(content)
        print(bottom)
        print("\n")
        sys.stdout.flush()

    # ONLY log to file - never duplicate to console
    logger.info(f"{Symbols.LIST} {header}")


def run_with_progress(items: List[Any], action_func: Callable[[Any], Any],
                     description: str = "Processing",
                     show_item_details: bool = False) -> List[Any]:
    """Run an action on each item with a progress bar and error handling.

    Args:
        items: Collection of items to process
        action_func: Function to call for each item
        description: Text description for the progress bar
        show_item_details: Whether to show item details in progress

    Returns:
        List of results from action_func
    """
    results = []
    success_count = 0
    error_count = 0

    # Don't create a progress bar for empty list
    if not items:
        log_info(f"{description}: No items to process")
        return results

    bar = ProgressBar(total=len(items), prefix=description)

    for i, item in enumerate(items):
        try:
            # Update prefix with item details if requested
            if show_item_details:
                bar.prefix = f"{description} - {str(item)[:20]}{'...' if len(str(item)) > 20 else ''}"

            # Process the item and track success/failure
            result = action_func(item)
            results.append(result)
            success_count += 1

        except Exception as e:
            # Log the error but continue processing
            log_error(f"Error processing item {i+1}/{len(items)}: {e}")
            results.append(None)  # Add None for failed items
            error_count += 1

        finally:
            # Always update the progress, regardless of success/failure
            bar.update(i + 1)

    # Complete the progress bar
    bar.finish()

    # Log summary
    log_info(f"{description} complete: {success_count} succeeded, {error_count} failed")

    return results


def log_step_start(step_name: str, step_number: Optional[int] = None,
                  total_steps: Optional[int] = None,
                  details: Optional[str] = None) -> None:
    """Log the start of a processing step with better formatting.

    Args:
        step_name: Name of the step
        step_number: Current step number (optional)
        total_steps: Total number of steps (optional)
        details: Additional details to include
    """
    # Ensure we're starting on a new line with extra space
    ensure_newline()

    # Build the message
    if step_number and total_steps:
        message = f"Step {step_number}/{total_steps}: {step_name}"
    else:
        message = step_name

    # Add optional details if provided
    if details:
        short_details = details[:40] + ("..." if len(details) > 40 else "")
        message = f"{message} ({short_details})"

    # Use a consistent symbol
    symbol = Symbols.START

    # Log to file only
    logger.info(f"{symbol} {message}")

    # Print to console with more spacing and color
    with console_lock:
        print(f"\n\033[36m{symbol} {message}\033[0m")
        sys.stdout.flush()


def log_step_end(step_name: str, status: str = "completed",
                time_taken: Optional[float] = None,
                details: Optional[str] = None,
                console_only: bool = False) -> None:
    """Log the end of a processing step with better formatting.

    Args:
        step_name: Name of the step
        status: Step status (completed, failed, etc)
        time_taken: Time taken to complete the step
        details: Additional details to include
        console_only: Only output to console, not log file
    """
    # Ensure we're starting on a new line
    ensure_newline()

    # Determine symbol based on status
    symbol = Symbols.SUCCESS if status.lower() == "completed" else Symbols.ERROR

    # Determine color based on status
    color = "\033[32m" if status.lower() == "completed" else "\033[31m"  # Green for success, Red for error

    # Build the message
    if time_taken:
        time_str = f" ({time_taken:.1f}s)"
    else:
        time_str = ""

    message = f"{step_name} {status}{time_str}"

    # Add details if provided
    if details:
        short_details = details[:40] + ("..." if len(details) > 40 else "")
        message = f"{message} - {short_details}"

    # Log to file
    if not console_only:
        logger.info(f"{symbol} {message}")

    # Print to console with consistent spacing and color
    with console_lock:
        print(f"{color}{symbol} {message}\033[0m\n")
        sys.stdout.flush()


def log_playlist_step(playlist_id: str, name: Optional[str] = None,
                     step: Optional[str] = None,
                     status: Optional[str] = None,
                     console_only: bool = False,
                     details: Optional[str] = None) -> None:
    """Log a single step of playlist processing with better formatting.

    Args:
        playlist_id: The Spotify playlist ID
        name: The playlist name
        step: The step being performed
        status: Step status
        console_only: Only output to console, not log file
        details: Additional details to include
    """
    # Ensure we're starting on a new line
    ensure_newline()

    # Handle cases where name might be None
    playlist_name = name if name else playlist_id
    short_id = playlist_id[:8] + "..." if len(playlist_id) > 8 else playlist_id

    # Determine the appropriate symbol
    if step:
        if "fetch" in step.lower() or "get" in step.lower():
            symbol = Symbols.SEARCH
        elif "match" in step.lower():
            symbol = Symbols.SYNC
        elif "track" in step.lower():
            symbol = Symbols.TRACKS
        elif "creat" in step.lower() or "updat" in step.lower():
            symbol = Symbols.PLAYLIST
        else:
            symbol = Symbols.INFO
    else:
        symbol = Symbols.PLAYLIST

    # Build a clean message
    if name:
        message = f"Playlist '{playlist_name}'"
        if step:
            message = f"{message}: {step}"
    else:
        message = f"Playlist {short_id}"
        if step:
            message = f"{message}: {step}"

    # Add status if provided
    if status:
        message = f"{message} - {status}"

    # Add details if provided, but keep it concise
    if details and len(details) < 40:
        message = f"{message} ({details})"

    # Log to file
    if not console_only:
        logger.info(f"{symbol} {message}")

    # Print to console with consistent spacing and indentation
    with console_lock:
        print(f"  {symbol} {message}")
        sys.stdout.flush()
