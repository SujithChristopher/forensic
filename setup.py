"""Setup configuration for Network Copy application"""

from setuptools import setup, find_packages

setup(
    name="netcpy",
    version="2.0.0",
    description="Network Copy - Raspberry Pi File Transfer Utility",
    author="Forensic System",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        "PySide6",
        "paramiko",
        "cryptography",
    ],
    entry_points={
        "console_scripts": [
            "netcpy=netcpy.main:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "License :: OSI Approved :: MIT License",
    ],
)
