#!/usr/bin/env python3
import argparse
import logging
import os
import re
import subprocess
import sys

# Define the standard name for the virtual environment directory
VENV_NAME = "env"


def parse_missing_module(stderr_output):
    """
    Parses stderr output to find the name of the missing module.
    It looks for standard 'No module named' or 'ImportError' messages.
    """
    patterns = [
        r"No module named '([^']*)'",
        r"No module named \"([^\"]*)\"",
        r"ImportError: No module named (\S+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, stderr_output)
        if match:
            return match.group(1)
    return None


def install_package(package_name, python_executable, assume_yes=False):
    """
    Installs a given package using pip into the specified python environment.
    Prompts the user for confirmation unless assume_yes is True.
    """
    if not package_name:
        return False, "No package name provided."

    if not assume_yes:
        try:
            prompt = input(
                f"Missing package '{package_name}'. Install with pip? [Y/n] "
            )
            if prompt.lower().strip() not in ["", "y", "yes"]:
                logging.warning(f"Skipping installation of '{package_name}'.")
                return False, f"User declined to install {package_name}."
        except KeyboardInterrupt:
            logging.info("\nInstallation cancelled by user.")
            sys.exit(1)

    logging.info(f"Attempting to install '{package_name}' with pip...")
    try:
        # Running pip as a module of the potentially virtualized python
        install_process = subprocess.run(
            [python_executable, "-m", "pip", "install", package_name],
            check=True,
            capture_output=True,
            text=True,
        )
        logging.info(f"Successfully installed '{package_name}'.")
        print(install_process.stdout)
        return True, ""
    except subprocess.CalledProcessError as e:
        error_message = f"Failed to install '{package_name}'.\n"
        error_message += f"pip exited with status {e.returncode}.\n"
        error_message += f"Stderr:\n{e.stderr}"
        return False, error_message
    except FileNotFoundError:
        error_message = f"Error: '{python_executable}' command not found. Is Python installed and in your PATH?"
        return False, error_message


def resolve_dependencies(script_path, timeout, assume_yes, python_executable):
    """
    Main loop to run the script, catch import errors, and install dependencies.
    """
    installed_packages = []
    max_retries = 20  # A safe limit to prevent infinite loops
    retries = 0

    while retries < max_retries:
        retries += 1
        logging.info(
            f"--- Attempt {retries}: Running '{script_path}' using '{python_executable}' ---"
        )
        try:
            # Execute the target script as a subprocess using the correct interpreter
            process = subprocess.run(
                [python_executable, script_path],
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            # Check stderr for import errors
            stderr_output = process.stderr
            if process.returncode != 0 and stderr_output:
                missing_module = parse_missing_module(stderr_output)
                if missing_module:
                    logging.info(f"Detected missing module: '{missing_module}'")

                    package_to_install = missing_module

                    success, message = install_package(
                        package_to_install, python_executable, assume_yes
                    )
                    if success:
                        installed_packages.append(package_to_install)
                        continue
                    else:
                        logging.error(f"Error: {message}")
                        logging.critical("Aborting due to installation failure.")
                        sys.exit(1)
                else:
                    logging.error(
                        "Script failed with an error that is not a recognized import error."
                    )
                    logging.error(f"Return Code: {process.returncode}")
                    print(f"\n--- STDOUT ---\n{process.stdout}")
                    print(f"\n--- STDERR ---\n{stderr_output}")
                    break
            else:
                logging.info("--- Script Execution Successful ---")
                logging.info("The script ran without any import errors.")
                print(f"\n--- STDOUT ---\n{process.stdout}")
                if process.stderr:
                    print(f"\n--- STDERR ---\n{process.stderr}")
                break

        except FileNotFoundError:
            logging.critical(
                f"Error: The script '{script_path}' or interpreter '{python_executable}' was not found."
            )
            sys.exit(1)
        except subprocess.TimeoutExpired:
            logging.warning("--- Script Execution Timed Out ---")
            logging.warning(
                f"The script ran for more than the specified timeout of {timeout} seconds without exiting."
            )
            logging.info("Assuming all dependencies are resolved.")
            break
        except Exception as e:
            logging.critical(f"An unexpected error occurred: {e}")
            sys.exit(1)

    if retries >= max_retries:
        logging.critical(
            "Reached maximum number of retries. Aborting to prevent infinite loop."
        )

    print("\n--- Dependency Resolution Summary ---")
    if installed_packages:
        print("Successfully installed the following packages:")
        for pkg in installed_packages:
            print(f"  - {pkg}")
    else:
        print("No new packages needed to be installed.")
    print("---------------------------------------")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Automatically detect and install missing Python packages for a script, with optional venv creation.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("script_path", help="The path to the Python script to run.")
    parser.add_argument(
        "--create-env",
        action="store_true",
        help=f"Create a virtual environment named '{VENV_NAME}' and install dependencies there.",
    )
    parser.add_argument(
        "--fork-timeout",
        type=int,
        default=15,
        help="Time in seconds to wait for the script to execute before timing out.\n(default: 15)",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Automatically answer 'yes' to all installation prompts.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Set the logging level (default: INFO)",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
    )

    python_executable = sys.executable

    if args.create_env:
        if os.path.exists(VENV_NAME):
            logging.warning(
                f"Directory '{VENV_NAME}' already exists. Using existing environment."
            )
        else:
            logging.info(f"Creating virtual environment '{VENV_NAME}'...")
            try:
                subprocess.run(
                    [sys.executable, "-m", "venv", VENV_NAME],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                logging.info("Successfully created virtual environment.")
            except subprocess.CalledProcessError as e:
                logging.critical(f"Failed to create virtual environment.\n{e.stderr}")
                sys.exit(1)

        # Determine the path to the python executable in the venv
        if sys.platform == "win32":
            python_executable = os.path.join(VENV_NAME, "Scripts", "python.exe")
        else:
            python_executable = os.path.join(VENV_NAME, "bin", "python")

        if not os.path.exists(python_executable):
            logging.critical(
                f"Could not find Python executable in venv at '{python_executable}'."
            )
            sys.exit(1)

        logging.info(f"Using Python interpreter from venv: '{python_executable}'")

    resolve_dependencies(
        args.script_path, args.fork_timeout, args.yes, python_executable
    )
