"""Root conftest for the census-us repo.

The package is installed editable (``pip install -e .``) so handler
modules resolve via the standard ``census_us.handlers.*`` path —
no ``sys.path`` gymnastics required.
"""

from __future__ import annotations
