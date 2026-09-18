#!/usr/bin/python3
"""Inspect Clockenstein's SQLite stores without starting the applications."""

import argparse
import os
import readline
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.text import Text
from setproctitle import setproctitle


HELP = """
Enter SQL or one of these commands:

  /calendar        Connect to the calendar database
  /alarms          Connect to the alarm database
  /tables          List tables and views
  /schema [table]  Show SQL definitions for all tables or one table
  /help            Show this help
  /quit, /exit     Exit

The selected database is opened read-only. Query results are not saved to disk.
"""


def _get_connection(path):
    # mode=ro also prevents creating an empty database if the path is wrong.
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def _print_query(connection, console, query, limit, parameters=()):
    with closing(connection.cursor()) as cursor:
        cursor.execute(query, parameters)
        if cursor.description is None:
            console.print("No result columns.")
            console.print()
            return
        table = Table(header_style="bold cyan")
        for column in cursor.description:
            table.add_column(Text(column[0]))
        rows = cursor.fetchmany(limit + 1)
        for row in rows[:limit]:
            cells = []
            for value in row:
                if value is None:
                    cells.append(Text("NULL", style="dim"))
                elif isinstance(value, bytes):
                    cells.append(Text("0x" + value.hex()))
                else:
                    # Event names and descriptions are data, not Rich markup.
                    cells.append(Text(str(value)))
            table.add_row(*cells)
        console.print(table)
        if len(rows) > limit:
            console.print(f"Showing the first {limit} rows. Use --limit to show more.")
        else:
            console.print(f"{len(rows)} row(s).")
        console.print()


def _run_command(connection, console, command, limit):
    if command == "/help":
        console.print(HELP, style="dark_orange")
        console.print()
    elif command == "/tables":
        _print_query(connection, console,
                     "SELECT name, type FROM sqlite_schema "
                     "WHERE type IN ('table', 'view') ORDER BY name", limit)
    elif command == "/schema" or command.startswith("/schema "):
        table_name = command[len("/schema"):].strip()
        query = "SELECT name, sql FROM sqlite_schema WHERE sql IS NOT NULL"
        parameters = ()
        if table_name:
            query += " AND tbl_name = ?"
            parameters = (table_name,)
        _print_query(connection, console, query + " ORDER BY name", limit, parameters)
    else:
        raise ValueError("Unknown command. Use /help for available commands.")


def _show_database(connection, console, path, limit):
    console.print(Text(f"{path.name} (read-only)", style="bold cyan"))
    _run_command(connection, console, "/tables", limit)


def _get_prompt(path, pending_command, color):
    marker = "…" if pending_command else "❯"
    if not color:
        return f"clockenstein {path.name} {marker} "
    # Readline must not count color escapes as visible prompt characters.
    cyan = "\001\033[1;36m\002"
    green = "\001\033[1;32m\002"
    reset = "\001\033[0m\002"
    return f"clockenstein {cyan}{path.name}{reset} {green}{marker}{reset} "


def _run_session(path, console, stream, limit):
    connection = _get_connection(path)
    interactive = stream.isatty()
    use_color = console.color_system is not None and not console.no_color
    if interactive:
        readline.parse_and_bind('"\\e[A": previous-history')
        readline.parse_and_bind('"\\e[B": next-history')
    pending_command = ""
    failed = False
    try:
        console.print(HELP, style="dark_orange")
        console.print()
        _show_database(connection, console, path, limit)
        while True:
            try:
                if interactive:
                    prompt = _get_prompt(path, pending_command, use_color)
                    try:
                        line = input(prompt) + "\n"
                    except EOFError:
                        console.print()
                        line = ""
                else:
                    line = stream.readline()
                if not line:
                    if pending_command:
                        raise ValueError("Command continuation is missing its next line.")
                    break
                line = line.rstrip()
                if line.endswith("\\"):
                    pending_command += line[:-1] + "\n"
                    continue
                command = (pending_command + line).strip()
                pending_command = ""
                if not command:
                    continue
                if command.startswith("/") and not command.startswith("/*"):
                    if command in ("/quit", "/exit"):
                        break
                    if command in ("/calendar", "/alarms"):
                        filename = "calendars.db" if command == "/calendar" else "alarms.db"
                        next_path = path.with_name(filename)
                        next_connection = _get_connection(next_path)
                        try:
                            _show_database(next_connection, console, next_path, limit)
                        except sqlite3.Error:
                            next_connection.close()
                            raise
                        connection.close()
                        connection = next_connection
                        path = next_path
                    else:
                        _run_command(connection, console, command, limit)
                    continue
                _print_query(connection, console, command, limit)
            except KeyboardInterrupt:
                console.print()
                pending_command = ""
            except (sqlite3.Error, ValueError) as error:
                console.print(Text(f"Error: {error}", style="red"))
                console.print()
                pending_command = ""
                failed = True
                if not line and not interactive:
                    break
    finally:
        connection.close()
    return int(failed)


def main(arguments=None):
    setproctitle("clockenstein-cli")
    parser = argparse.ArgumentParser(prog="clockenstein-cli", description=__doc__)
    parser.add_argument("database", choices=("calendar", "calendars", "alarms"),
                        nargs="?", default="calendar")
    parser.add_argument("--data-dir", type=Path,
                        default=os.environ.get("CLOCKENSTEIN_DATA_DIR", "~/.local/share/clockenstein"),
                        help="Clockenstein data directory (also set by CLOCKENSTEIN_DATA_DIR)")
    parser.add_argument("-q", "--query", help="Run one SQL statement and exit")
    parser.add_argument("--limit", type=int, default=200, help="Maximum displayed rows (default: 200)")
    options = parser.parse_args(arguments)
    if options.limit < 1:
        parser.error("--limit must be at least 1")
    filename = "alarms.db" if options.database == "alarms" else "calendars.db"
    path = options.data_dir.expanduser() / filename
    console = Console(highlight=False, markup=False)
    try:
        if options.query is not None:
            with closing(_get_connection(path)) as connection:
                _print_query(connection, console, options.query, options.limit)
                return 0
        if sys.stdin.isatty():
            console.print("Clockenstein CLI")
        return _run_session(path, console, sys.stdin, options.limit)
    except (OSError, sqlite3.Error) as error:
        error_console = Console(stderr=True)
        error_console.print(Text(f"Error: {path}: {error}", style="red"))
        error_console.print()
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
