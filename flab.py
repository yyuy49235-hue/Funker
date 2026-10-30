"""Run the engine from Termux/PC:  python3 flab.py scan "<mod folder>"  (see README)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app", "src", "main", "python"))
from funkerlitelab.cli import main
main()
