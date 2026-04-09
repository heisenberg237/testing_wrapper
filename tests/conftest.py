"""Pytest configuration: set env for config paths before imports."""

import os

import pytest


def pytest_configure(config):
    """Set MLE_PROJECT_ROOT so config resolves to project dir (avoid PermissionError)."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if "MLE_PROJECT_ROOT" not in os.environ:
        os.environ["MLE_PROJECT_ROOT"] = root
    if "MLE_CONFIG_DIR" not in os.environ:
        os.environ["MLE_CONFIG_DIR"] = os.path.join(root, "config")
