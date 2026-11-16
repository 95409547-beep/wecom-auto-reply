"""Writable application assets live beside the EXE, never in its extraction dir."""
import sys
from pathlib import Path


def app_dir():
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
