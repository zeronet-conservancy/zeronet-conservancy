import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
src_path = os.path.join(current_dir, 'src')
if src_path not in sys.path:
    sys.path.insert(0, os.path.join(src_path, 'lib'))
    sys.path.insert(0, src_path)
