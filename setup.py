from setuptools import setup, find_packages

setup(
    name="altotrader",  
    author="Maximilian Hansinger",
    version="0.1.0",    # Version number
    packages=find_packages(where="src"),  # Find packages inside the `src` directory
    package_dir={"": "src"},  # Tell setuptools that the packages are inside `src`
    install_requires=[  # List of runtime dependencies
    ],
    extras_require={  # Optional dependencies, e.g., for development
        "dev": [
            "pytest>=6.0",
            "tox>=3.0",
        ],
    },
    tests_require=["pytest"],  # Specify testing dependencies
    test_suite="tests",  # Point to your test suite
)

