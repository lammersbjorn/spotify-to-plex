"""Utility functions and classes for enhanced logging and output formatting.

This module provides helper functions for logging, progress bar management, and output formatting.
All public functions and classes include Google-style docstrings and full type annotations.
"""

from collections.abc import Callable
import os
import subprocess
import sys
import threading
import time
from typing import Any, Optional, TypeVar

from loguru import logger
import rtoml

T = TypeVar("T")


class Symbols:
    """Container for terminal-safe symbols used across the module."""

    # General Status
    INFO = "•"
    DEBUG = "⋯"
    WARNING = "!"
    ERROR = "✗"
    SUCCESS = "✓"

    # Media / Specific Apps
    MUSIC = "♪"
    PLAYLIST = "♫"
    USER = "●"
    USERS = "◎"
    SPOTIFY = "♫"
    PLEX = "▶"
    TRACK = "•"
    TRACKS = "::"

    # Actions / Processes
    PROCESSING = ">"
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


class Colors:
    """ANSI color codes for terminal output."""
    RESET = "\033[0m"
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    UNDERLINE = "\033[4m"

    # Predefined combinations for log levels
    INFO = CYAN
    DEBUG = DIM
    WARNING = YELLOW
    ERROR = RED
    SUCCESS = GREEN
    HEADER = BOLD + BLUE
    PLAYLIST = MAGENTA
    PROGRESS = BLUE


console_lock = threading.RLock()


def get_version() -> str:
    """Retrieve the current version of the application.

    The function attempts to get version information by:
      1. Querying Git tags.
      2. Reading the version from a pyproject.toml file.
      3. Reading a VERSION file from common locations.
      4. Falling back to a hardcoded version.

    Returns:
        str: The determined version string.
    """
    # Attempt to get version from Git
    try:
        version = (
            subprocess.check_output(
                ["git", "describe", "--tags", "--abbrev=0"],
                stderr=subprocess.DEVNULL,
            )
            .decode("utf-8")
            .strip()
        )
        if version:
            return version
    except (subprocess.SubprocessError, FileNotFoundError):
        logger.debug("Could not get version from git")

    # Try to read version from pyproject.toml
    try:
        possible_toml_paths = [
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "pyproject.toml",
            ),
            "pyproject.toml",
            os.path.join(os.getcwd(), "pyproject.toml"),
        ]
        for toml_path in possible_toml_paths:
            if os.path.exists(toml_path):
                try:
                    with open(toml_path, encoding="utf-8") as f:
                        config = rtoml.load(f)
                    if config and "tool" in config and "poetry" in config["tool"]:
                        version = config["tool"]["poetry"].get("version")
                        if version:
                            logger.debug(
                                f"Retrieved version {version} from pyproject.toml"
                            )
                            return version
                except (rtoml.RTomlError, OSError) as e:
                    logger.debug(f"Error reading version from {toml_path}: {e}")
    except OSError as e:
        logger.debug(f"Error processing pyproject.toml: {e}")

    # Check VERSION file from common locations
    possible_paths = [
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "VERSION"
        ),
        "VERSION",
        os.path.join(os.getcwd(), "VERSION"),
    ]
    for path in possible_paths:
        try:
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    version = f.read().strip()
                if version:
                    logger.debug(f"Retrieved version {version} from {path}")
                    return version
        except OSError as e:
            logger.debug(f"Error reading version from {path}: {e}")

    logger.debug("Using fallback version")
    return "0.0.0"


def perform_task(func: Callable[..., T], message: str, *args: Any, **kwargs: Any) -> T:
    """Execute a callable with a status message and error handling.

    Args:
        func (Callable[..., T]): The function to execute.
        message (str): A description for the task.
        *args: Positional arguments for the function.
        **kwargs: Keyword arguments for the function.

    Returns:
        T: The result returned by func.

    Raises:
        Exception: Re-raises any exception encountered during function execution.
    """
    log_info(f"Task: {message}", Symbols.PROCESSING)
    try:
        result = func(*args, **kwargs)
        log_debug(f"Task completed: {message}", Symbols.SUCCESS)
        return result
    except Exception as err:
        log_error(f"Task failed: {message} - {err}")
        raise


class ProgressBar:
    """Text-based progress bar with percentage indicator and spinner."""

    def __init__(
        self, total: int, prefix: str = "", suffix: str = "", length: int = 30
    ) -> None:
        """Initialize a ProgressBar instance.

        Args:
            total (int): Total number of steps.
            prefix (str, optional): Text displayed before the bar. Defaults to "".
            suffix (str, optional): Text displayed after the bar. Defaults to "".
            length (int, optional): Character length of the bar. Defaults to 30.
        """
        self.total = max(1, total)
        self.prefix = prefix
        self.suffix = suffix
        self.length = length
        self.current = 0
        self.start_time = time.time()
        self._lock = threading.RLock()
        self._last_line_length = 0
        self._line_active = False
        self._spinner_idx = 0
        self._spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self._last_percentage = -1  # Track last percentage for non-TTY environments

    def update(self, current: Optional[int] = None) -> None:
        """Update the progress bar display.

        Args:
            current (Optional[int], optional): New progress value. If None, increments by one. Defaults to None.
        """
        with self._lock:
            self.current = current if current is not None else self.current + 1
            self.current = min(self.current, self.total)
            self._spinner_idx = (self._spinner_idx + 1) % len(self._spinner_chars)
            spinner_char = self._spinner_chars[self._spinner_idx]
            percent = 100 * (self.current / self.total)
            elapsed = time.time() - self.start_time
            eta = "N/A"
            if self.current > 0:
                eta_seconds = elapsed * (self.total - self.current) / self.current
                eta = (
                    f"{eta_seconds:.0f}s"
                    if eta_seconds < 60
                    else (
                        f"{eta_seconds/60:.1f}m"
                        if eta_seconds < 3600
                        else f"{eta_seconds/3600:.1f}h"
                    )
                )
            filled_length = int(self.length * self.current // self.total)
            bar = "#" * filled_length + "-" * (self.length - filled_length)

            if not sys.stdout.isatty():
                # For non-TTY environments, only print when percentage changes or at beginning/end
                current_percent_int = int(percent)
                if (current_percent_int != self._last_percentage) or (self.current == self.total) or (self.current == 1):
                    with console_lock:
                        print(f"Progress: [{bar}] {percent:.1f}% ({self.current}/{self.total}) {self.suffix}")
                    self._last_percentage = current_percent_int
                return

            # TTY environment - use spinner and in-place updates
            with console_lock:
                if not self._line_active:
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                line = f"{spinner_char} {self.prefix} [{bar}] {percent:.1f}% ({self.current}/{self.total}) {self.suffix}"
                sys.stdout.write("\r" + " " * self._last_line_length + "\r")
                sys.stdout.write(line)
                sys.stdout.flush()
                self._last_line_length = len(line)
                self._line_active = True

    def clear_line(self) -> None:
        """Clear the current progress bar line."""
        with self._lock:
            if self._line_active:
                with console_lock:
                    sys.stdout.write("\r" + " " * self._last_line_length + "\r")
                    sys.stdout.flush()
                self._line_active = False

    def ensure_newline(self) -> None:
        """Ensure subsequent output appears on a new line."""
        with self._lock:
            if self._line_active:
                with console_lock:
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                self._line_active = False

    def finish(self) -> None:
        """Complete the progress bar and display timing information."""
        with self._lock:
            self.update(self.total)
            elapsed = time.time() - self.start_time
            time_str = f"{elapsed:.1f}s" if elapsed < 60 else f"{elapsed/60:.1f}m"
            with console_lock:
                sys.stdout.write(f" (completed in {time_str})\n")
                sys.stdout.flush()
            self._line_active = False


def setup_logging(log_level: str = "INFO", log_dir: str = "logs") -> None:
    """Configure logging with file-based output.

    Args:
        log_level (str, optional): Minimum console log level. Defaults to "INFO".
        log_dir (str, optional): Directory to store log files. Defaults to "logs".
    """
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError as err:
        logger.warning(f"Could not create log directory {log_dir}: {err}")
        log_dir = "."

    file_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "{message}"
    )
    logger.remove()
    try:
        logger.add(
            f"{log_dir}/spotify_to_plex_{{time:YYYY-MM-DD}}.log",
            format=file_format,
            level="DEBUG",
            rotation="12:00",
            retention="7 days",
            compression="zip",
            backtrace=True,
            diagnose=True,
            enqueue=True,
        )
    except OSError as err:
        logger.warning(f"Could not set up file logger: {err}")

    # Intercept standard library root logger warnings
    import logging

    class RootLoggerHandler(logging.Handler):
        def emit(self, record):
            # Map standard logging levels to our custom log functions
            if record.levelno >= logging.ERROR:
                log_error(record.getMessage())
            elif record.levelno >= logging.WARNING:
                log_warning(record.getMessage())
            elif record.levelno >= logging.INFO:
                log_info(record.getMessage())
            else:
                log_debug(record.getMessage())

    # Configure root logger to use our handler
    root_logger = logging.getLogger()
    root_logger.handlers = []  # Remove existing handlers
    root_logger.addHandler(RootLoggerHandler())
    root_logger.setLevel(logging.INFO)  # Set appropriate level


def draw_box(text: str, padding: int = 2, width: int = 50, align: str = "left", extra_width: int = 0) -> tuple[str, str, str]:
    """Draw a box around the provided text.

    Args:
        text (str): Text to enclose in a box.
        padding (int, optional): Horizontal padding. Defaults to 2.
        width (int, optional): Fixed width for the box content. Defaults to 50.
        align (str, optional): Text alignment - "left", "center", or "right". Defaults to "left".
        extra_width (int, optional): Additional width (legacy parameter). Defaults to 0.

    Returns:
        Tuple[str, str, str]: The top border, content line, and bottom border.
    """
    text_width = len(text)

    # Add extra_width for backward compatibility
    if extra_width > 0:
        width += extra_width

    # Calculate text positioning
    if align == "center":
        left_space = (width - text_width) // 2
        right_space = width - text_width - left_space
    elif align == "right":
        left_space = width - text_width - padding
        right_space = padding
    else:  # left alignment
        left_space = padding
        right_space = width - text_width - left_space

    top_border = f"┏{'━' * width}┓"
    content_line = f"┃{' ' * left_space}{text}{' ' * right_space}┃"
    bottom_border = f"┗{'━' * width}┛"

    return top_border, content_line, bottom_border


_current_progress_bar: Optional[ProgressBar] = None
_last_output_was_newline = False


def set_active_progress_bar(bar: Optional[ProgressBar]) -> None:
    """Set the active progress bar.

    Args:
        bar (Optional[ProgressBar]): Instance to mark as active.
    """
    global _current_progress_bar
    _current_progress_bar = bar


def ensure_newline() -> None:
    """Ensure subsequent output starts on a new line to avoid overlap."""
    global _current_progress_bar, _last_output_was_newline
    with console_lock:
        if _current_progress_bar is not None and _current_progress_bar._line_active:
            _current_progress_bar.ensure_newline()
            _last_output_was_newline = True
        elif not _last_output_was_newline:
            # Only print a newline if we're not already at a new line
            sys.stdout.write("\r")  # Move to beginning of line
            sys.stdout.flush()
            _last_output_was_newline = True


def log(
    level: str,
    message: str,
    symbol: Optional[str] = None,
    console_only: bool = False,
    file_only: bool = False,
    ensure_line_break: bool = True,
    **context: Any,
) -> None:
    """Log a message with the specified level.

    Args:
        level (str): Log level.
        message (str): Message text.
        symbol (Optional[str], optional): Symbol to use. Defaults to None.
        console_only (bool, optional): Log only to console. Defaults to False.
        file_only (bool, optional): Log only to file. Defaults to False.
        ensure_line_break (bool, optional): Force a new line before output. Defaults to True.
        **context: Additional logging context.
    """
    global _last_output_was_newline

    if ensure_line_break:
        ensure_newline()

    formatted_symbol = f"{symbol}" if symbol else ""

    # Select color based on log level
    color = Colors.RESET
    if level == "INFO":
        color = Colors.INFO
    elif level == "WARNING":
        color = Colors.WARNING
    elif level == "ERROR":
        color = Colors.ERROR
    elif level == "SUCCESS":
        color = Colors.SUCCESS
    elif level == "DEBUG":
        color = Colors.DEBUG

    with console_lock:
        if not file_only:
            if formatted_symbol:
                print(f"{color}{formatted_symbol} {message}{Colors.RESET}")
            else:
                print(f"{color}{message}{Colors.RESET}")
            _last_output_was_newline = False

        if not console_only:
            logger.log(level, message, **context)


def log_info(
    message: str,
    symbol: Optional[str] = None,
    console_only: bool = False,
    **context: Any,
) -> None:
    """Log an informational message.

    Args:
        message (str): Message text.
        symbol (Optional[str], optional): Override symbol. Defaults to None.
        console_only (bool, optional): Log only to console. Defaults to False.
        **context: Additional logging context.
    """
    if symbol in (Symbols.TRACK, Symbols.TRACKS, Symbols.MUSIC):
        ensure_newline()
    log("INFO", message, symbol or Symbols.INFO, console_only, **context)


def log_debug(
    message: str,
    symbol: Optional[str] = None,
    console_only: bool = False,
    file_only: bool = True,
    **context: Any,
) -> None:
    """Log a debug message.

    Args:
        message (str): Message text.
        symbol (Optional[str], optional): Override symbol. Defaults to None.
        console_only (bool, optional): Log only to console. Defaults to False.
        file_only (bool, optional): Log only to file. Defaults to True.
        **context: Additional logging context.
    """
    log("DEBUG", message, symbol or Symbols.DEBUG, console_only, file_only, **context)


def log_warning(
    message: str,
    symbol: Optional[str] = None,
    console_only: bool = False,
    **context: Any,
) -> None:
    """Log a warning message.

    Args:
        message (str): Message text.
        symbol (Optional[str], optional): Override symbol. Defaults to None.
        console_only (bool, optional): Log only to console. Defaults to False.
        **context: Additional logging context.
    """
    log("WARNING", message, symbol or Symbols.WARNING, console_only, **context)


def log_error(
    message: str,
    symbol: Optional[str] = None,
    console_only: bool = False,
    **context: Any,
) -> None:
    """Log an error message.

    Args:
        message (str): Message text.
        symbol (Optional[str], optional): Override symbol. Defaults to None.
        console_only (bool, optional): Log only to console. Defaults to False.
        **context: Additional logging context.
    """
    log("ERROR", message, symbol or Symbols.ERROR, console_only, **context)


def log_success(
    message: str,
    symbol: Optional[str] = None,
    console_only: bool = False,
    **context: Any,
) -> None:
    """Log a success message.

    Args:
        message (str): Message text.
        symbol (Optional[str], optional): Override symbol. Defaults to None.
        console_only (bool, optional): Log only to console. Defaults to False.
        **context: Additional logging context.
    """
    log("SUCCESS", message, symbol or Symbols.SUCCESS, console_only, **context)


def log_header(message: str) -> None:
    """Log a header message with distinct formatting.

    Args:
        message (str): Header text.
    """
    global _last_output_was_newline
    header = message.upper()

    # Only add a single newline before headers if we're not already at a new line
    if not _last_output_was_newline:
        with console_lock:
            sys.stdout.write("\n")
            sys.stdout.flush()

    # Updated to use the new draw_box signature without extra_width parameter
    top, content, bottom = draw_box(header, padding=4)
    with console_lock:
        sys.stdout.write(f"{Colors.HEADER}{top}\n{content}\n{bottom}{Colors.RESET}\n")
        sys.stdout.flush()
        _last_output_was_newline = False

    logger.info(f"{Symbols.LIST} {header}")


def run_with_progress(
    items: list[Any],
    action_func: Callable[[Any], Any],
    description: str = "Processing",
    show_item_details: bool = False,
) -> list[Any]:
    """Apply a function to each item while displaying a progress bar.

    Args:
        items (list[Any]): Iterable of items.
        action_func (Callable[[Any], Any]): Function to be applied to each item.
        description (str, optional): Description prefix for the progress bar. Defaults to "Processing".
        show_item_details (bool, optional): Toggle to show detail per item. Defaults to False.

    Returns:
        list[Any]: List of results (or None for items that failed).
    """
    global _last_output_was_newline
    results: list[Any] = []
    success_count = 0
    error_count = 0

    if not items:
        log_info(f"{description}: No items to process")
        return results

    bar = ProgressBar(total=len(items), prefix=description)

    for i, item in enumerate(items):
        try:
            if show_item_details:
                detail = str(item)[:20]
                bar.prefix = (
                    f"{description} - {detail}{'...' if len(str(item)) > 20 else ''}"
                )
            result = action_func(item)
            results.append(result)
            success_count += 1
        except (OSError, ValueError) as err:
            log_error(f"Error processing item {i+1}/{len(items)}: {err}")
            results.append(None)
            error_count += 1
        finally:
            bar.update(i + 1)

    bar.finish()
    log_info(f"{description} complete: {success_count} succeeded, {error_count} failed")
    _last_output_was_newline = False
    return results


def log_step_start(
    step_name: str,
    step_number: Optional[int] = None,
    total_steps: Optional[int] = None,
    details: Optional[str] = None,
) -> None:
    """Log the beginning of a processing step.

    Args:
        step_name (str): Name of the step.
        step_number (Optional[int], optional): Current step number. Defaults to None.
        total_steps (Optional[int], optional): Total steps count. Defaults to None.
        details (Optional[str], optional): Additional details. Defaults to None.
    """
    global _last_output_was_newline

    # Only ensure a newline for major steps
    ensure_newline()

    message = (
        f"Step {step_number}/{total_steps}: {step_name}"
        if step_number and total_steps
        else step_name
    )
    if details:
        short_details = details[:40] + ("..." if len(details) > 40 else "")
        message = f"{message} ({short_details})"

    symbol = Symbols.START
    logger.info(f"{symbol} {message}")

    with console_lock:
        sys.stdout.write(f"{Colors.BLUE}{symbol} {message}{Colors.RESET}\n")
        sys.stdout.flush()
        _last_output_was_newline = False


def log_step_end(
    step_name: str,
    status: str = "completed",
    time_taken: Optional[float] = None,
    details: Optional[str] = None,
    console_only: bool = False,
) -> None:
    """Log the completion of a processing step.

    Args:
        step_name (str): Name of the step.
        status (str, optional): Status string. Defaults to "completed".
        time_taken (Optional[float], optional): Duration in seconds. Defaults to None.
        details (Optional[str], optional): Additional details. Defaults to None.
        console_only (bool, optional): Log only to console. Defaults to False.
    """
    symbol = Symbols.SUCCESS if status.lower() == "completed" else Symbols.ERROR
    color = Colors.SUCCESS if status.lower() == "completed" else Colors.ERROR

    time_str = f" ({time_taken:.1f}s)" if time_taken else ""
    message = f"{step_name} {status}{time_str}"

    if details:
        short_details = details[:40] + ("..." if len(details) > 40 else "")
        message = f"{message} - {short_details}"

    if not console_only:
        logger.info(f"{symbol} {message}")

    with console_lock:
        sys.stdout.write(f"{color}{symbol} {message}{Colors.RESET}\n")
        sys.stdout.flush()
        _last_output_was_newline = False


def log_playlist_step(
    playlist_id: str,
    name: Optional[str] = None,
    step: Optional[str] = None,
    status: Optional[str] = None,
    console_only: bool = False,
    details: Optional[str] = None,
) -> None:
    """Log a specific step in playlist processing.

    Args:
        playlist_id (str): Spotify playlist identifier.
        name (Optional[str], optional): Playlist name. Defaults to None.
        step (Optional[str], optional): Current step description. Defaults to None.
        status (Optional[str], optional): Step status. Defaults to None.
        console_only (bool, optional): Log to console only. Defaults to False.
        details (Optional[str], optional): Additional details. Defaults to None.
    """
    global _last_output_was_newline

    # Only ensure line break if we're in the middle of a progress bar
    if _current_progress_bar is not None and _current_progress_bar._line_active:
        _current_progress_bar.ensure_newline()

    playlist_name = name if name else playlist_id
    short_id = playlist_id[:8] + "..." if len(playlist_id) > 8 else playlist_id

    # Choose appropriate symbol and color based on step type
    if step:
        if "found" in step.lower() or "complet" in step.lower() or "success" in step.lower():
            symbol = Symbols.SUCCESS
            color = Colors.SUCCESS
        elif "fetch" in step.lower() or "get" in step.lower():
            symbol = Symbols.INFO
            color = Colors.INFO
        elif "match" in step.lower():
            symbol = Symbols.SYNC
            color = Colors.INFO
        elif "track" in step.lower():
            symbol = Symbols.TRACKS
            color = Colors.INFO
        elif "creat" in step.lower() or "updat" in step.lower():
            symbol = Symbols.PLAYLIST
            color = Colors.PLAYLIST
        elif "error" in step.lower() or "fail" in step.lower():
            symbol = Symbols.ERROR
            color = Colors.ERROR
        else:
            symbol = Symbols.INFO
            color = Colors.INFO
    else:
        symbol = Symbols.PLAYLIST
        color = Colors.PLAYLIST

    # Format message
    message = f"Playlist: {playlist_name}" if name else f"Playlist: {short_id}"
    if step:
        message = f"{step} ({playlist_name})"
    if status:
        message = f"{message} - {status}"
    if details and len(details) < 40:
        message = f"{message} ({details})"

    if not console_only:
        logger.info(f"{symbol} {message}")

    with console_lock:
        sys.stdout.write(f"  {color}{symbol} {message}{Colors.RESET}\n")
        sys.stdout.flush()
        _last_output_was_newline = False
