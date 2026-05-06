# 0. Clean
Remove-Item .mypy_cache -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item .pytest_cache -Recurse -Force -ErrorAction SilentlyContinue

# 1. Syntax ALL app/
python -m py_compile app/**/*.py 2>nul

# 2. Dev tools (done)
pip install pytest pytest-cov mypy pytest-asyncio types-requests

# 3. pytest + COVERAGE FIX
pytest tests/ -v --asyncio-mode=auto --cov=app/scrapers --cov-report=html --cov-report=term-missing

# 4. mypy clean
mypy app/ --config-file mypy.ini

# 5. MASTER TEST
python -m tests.test_scrapers

# 6. Coverage HTML
start htmlcov/index.html



# 1. Syntax check (find scrapers dir first)
#Get-ChildItem -Recurse -Directory *scraper* | % { python -m py_compile $_.FullName\*.py }

# Install dev tools (one-time)
#pip install pytest pytest-cov mypy

# 2. Coverage
#pytest tests/ --cov=scrapers --cov-report=term-missing  # Post-install

# 3. Python abstract (in base_scraper.py)
