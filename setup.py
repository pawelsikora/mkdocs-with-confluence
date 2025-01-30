from setuptools import setup, find_packages

setup(
    name="mkdocs-with-confluence",
    version="0.2.8",
    description="MkDocs plugin for uploading markdown documentation to Confluence via Confluence REST API",
    keywords="mkdocs markdown confluence documentation rest python",
    url="https://github.com/pawelsikora/mkdocs-with-confluence/",
    author="Pawel Sikora",
    author_email="sikor6@gmail.com",
    license="MIT",
    python_requires=">=3.6",
    install_requires=["mkdocs>=1.1", "jinja2", "mistune", "md2cf", "requests"],
    packages=find_packages(),
    entry_points={"mkdocs.plugins": ["mkdocs-with-confluence = mkdocs_with_confluence.plugin:MkdocsWithConfluence"]},
)
