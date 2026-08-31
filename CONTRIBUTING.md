# Contributing

Contributions are welcome when they preserve the project's safety boundaries and license terms.

## Before submitting

1. Use Windows 10/11 and Python 3.10 or newer for runtime testing.
2. Run `python -m py_compile windows_app_locker.py`.
3. Run `python scripts/check_release.py`.
4. Run `python windows_app_locker.py --doctor` on a Windows test machine after installing dependencies.
5. Never commit bot tokens, Chat IDs tied to private data, configuration files, logs, or runtime state.

## Scope

Good contributions include UI fixes, compatibility improvements, documentation, safer validation, diagnostics, installer improvements, and registered-application controls.

Do not add arbitrary remote shell execution, keylogging, covert monitoring, credential capture, remote screenshots, hidden persistence, or unrelated surveillance functionality.

By contributing, you agree that your contribution is distributed under the repository's existing license.
