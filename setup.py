"""Setup script for MLE Heatmap Wrapper."""

from pathlib import Path

from setuptools import find_packages, setup

readme_file = Path(__file__).parent / "README.md"
long_description = readme_file.read_text(encoding="utf-8") if readme_file.exists() else ""

setup(
    name="mle-heatmap-wrapper",
    version="1.1.0",
    author="Jordan",
    description="Wrapper for MLE heatmap geometric calculations",
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.9",
    install_requires=[
        "pandas>=2.0.0",
        "numpy>=1.24.0",
        "pyyaml>=6.0",
        "python-dotenv>=1.0.0",
        "scipy>=1.10.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.4.0",
            "pytest-cov>=4.1.0",
            "black>=23.0.0",
            "flake8>=6.0.0",
            "mypy>=1.5.0",
        ]
    },
    entry_points={
        "console_scripts": [
            "mle-heatmap=mle_heatmap_wrapper.cli.main:main",
        ]
    },
    include_package_data=True,
)
