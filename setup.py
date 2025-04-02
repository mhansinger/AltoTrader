from setuptools import setup, find_packages
from pathlib import Path

requirements = Path("requirements.txt").read_text().splitlines()

setup(
    name="altotrader",
    author="mhansinger",
    version="0.1.0",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    install_requires=requirements,
    python_requires=">=3.11",
    tests_require=["pytest"],
    test_suite="Tests",
)
