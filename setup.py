from setuptools import setup, find_packages

setup(
    name="ai-stock-photo-api",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "pytrends>=4.9.2",
        "requests>=2.31.0",
        "Pillow>=10.1.0"
    ]
)
