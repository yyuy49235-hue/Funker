import os, sys, unittest
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "app", "src", "main", "python"))
suite = unittest.defaultTestLoader.discover(os.path.join(here, "tests"))
sys.exit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
