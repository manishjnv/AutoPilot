"""`python -m autopilot`: works even when the `autopilot` command is not on PATH."""
import sys

from .cli import main

sys.exit(main())
