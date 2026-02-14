$ErrorActionPreference = "Stop"

python -m pip install -e .
python -m unittest discover -s tests -p "test_*.py" -v
