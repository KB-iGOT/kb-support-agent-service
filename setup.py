"""
Setup

"""
from setuptools import setup, find_packages

with open("README.md", encoding="utf-8") as f:
    readme = f.read()

setup(
    name="kb-support-agent-service",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "google-generativeai",
        "python-dotenv",
        "fastapi",
        "uvicorn",
    ],
    author="iGOT Team",
    author_email="igot@support.com",
    description="An AI assistant for iGOT platform using LangChain and Google Gemini",
    long_description=readme,
    long_description_content_type="text/markdown",
    url="https://github.com/KB-iGOT/kb-support-agent-service.git",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.8",
)
