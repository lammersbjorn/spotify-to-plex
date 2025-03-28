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
	INFO = "ℹ"
	DEBUG = "»"
	WARNING = "▲"
	ERROR = "✖"
	SUCCESS = "✔"

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
				with console_lock:
					print(f"{spinner_char} {self.prefix} [{bar}] {percent:.1f}% ({self.current}/{self.total}) {self.suffix}")
				return

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


def draw_box(text: str, padding: int = 2, extra_width: int = 0) -> tuple[str, str, str]:
	"""Draw a box around the provided text.

	Args:
	    text (str): Text to enclose in a box.
	    padding (int, optional): Horizontal padding. Defaults to 2.
	    extra_width (int, optional): Additional width to be added. Defaults to 0.

	Returns:
	    Tuple[str, str, str]: The top border, content line, and bottom border.
	"""
	text_width = len(text)
	box_width = text_width + (padding * 2) + extra_width
	top_border = f"┏{'━' * box_width}┓"
	content_line = f"┃{' ' * padding}{text}{' ' * (padding + extra_width)}┃"
	bottom_border = f"┗{'━' * box_width}┛"
	return top_border, content_line, bottom_border


_current_progress_bar: Optional[ProgressBar] = None


def set_active_progress_bar(bar: Optional[ProgressBar]) -> None:
	"""Set the active progress bar.

	Args:
	    bar (Optional[ProgressBar]): Instance to mark as active.
	"""
	global _current_progress_bar
	_current_progress_bar = bar


def ensure_newline() -> None:
	"""Ensure subsequent output starts on a new line to avoid overlap."""
	global _current_progress_bar
	with console_lock:
		if _current_progress_bar is not None and _current_progress_bar._line_active:
			_current_progress_bar.ensure_newline()
		else:
			sys.stdout.write("\r\n")
			sys.stdout.flush()


def log(
	level: str,
	message: str,
	symbol: Optional[str] = None,
	console_only: bool = False,
	file_only: bool = False,
	**context: Any,
) -> None:
	"""Log a message with the specified level and symbol.

	Args:
	    level (str): Logging level (info, debug, warning, error, success).
	    message (str): The message to log.
	    symbol (Optional[str], optional): Override symbol. Defaults to None.
	    console_only (bool, optional): Log only to console. Defaults to False.
	    file_only (bool, optional): Log only to file. Defaults to False.
	    **context: Additional context for the logger.
	"""
	ensure_newline()
	if symbol is None:
		symbol = getattr(Symbols, level.upper(), Symbols.INFO)
	formatted_msg = f"{symbol} {message}"
	color_map = {
		"info": "\033[0m",
		"debug": "\033[36m",
		"warning": "\033[33m",
		"error": "\033[31m",
		"success": "\033[32m",
	}
	color = color_map.get(level.lower(), "\033[0m")
	reset = "\033[0m"

	if file_only:
		getattr(logger, level.lower())(formatted_msg, **context)
	elif console_only:
		with console_lock:
			sys.stdout.write(f"{color}{formatted_msg}{reset}\n")
			sys.stdout.flush()
	else:
		getattr(logger, level.lower())(formatted_msg, **context)
		with console_lock:
			sys.stdout.write(f"{color}{formatted_msg}{reset}\n")
			sys.stdout.flush()


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
	header = message.upper()
	with console_lock:
		sys.stdout.write("\n")
		top, content, bottom = draw_box(header, padding=4, extra_width=2)
		sys.stdout.write(f"{top}\n{content}\n{bottom}\n")
		sys.stdout.flush()
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
		sys.stdout.write(f"\n\033[36m{symbol} {message}\033[0m\n")
		sys.stdout.flush()


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
	ensure_newline()
	symbol = Symbols.SUCCESS if status.lower() == "completed" else Symbols.ERROR
	color = "\033[32m" if status.lower() == "completed" else "\033[31m"
	time_str = f" ({time_taken:.1f}s)" if time_taken else ""
	message = f"{step_name} {status}{time_str}"
	if details:
		short_details = details[:40] + ("..." if len(details) > 40 else "")
		message = f"{message} - {short_details}"
	if not console_only:
		logger.info(f"{symbol} {message}")
	with console_lock:
		sys.stdout.write(f"{color}{symbol} {message}\033[0m\n")
		sys.stdout.flush()


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
	ensure_newline()
	playlist_name = name if name else playlist_id
	short_id = playlist_id[:8] + "..." if len(playlist_id) > 8 else playlist_id
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
	message = f"Playlist '{playlist_name}'" if name else f"Playlist {short_id}"
	if step:
		message = f"{message}: {step}"
	if status:
		message = f"{message} - {status}"
	if details and len(details) < 40:
		message = f"{message} ({details})"
	if not console_only:
		logger.info(f"{symbol} {message}")
	with console_lock:
		sys.stdout.write(f"  {symbol} {message}\n")
		sys.stdout.flush()
