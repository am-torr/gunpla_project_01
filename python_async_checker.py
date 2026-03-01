# Async pytest
pip install pytest-asyncio
pytest tests/ -v --asyncio-mode=auto --cov=app/scrapers --cov-report=term-missing

# mypy types
mypy app/ --ignore-missing-imports

# Permission py_compile
Start-Process powershell -Verb RunAs -ArgumentList "-Command cd 'D:\PROJECT\gunpla-tracker-verified'; python -m py_compile app/scrapers/*.py"
