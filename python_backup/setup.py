from setuptools import find_packages, setup


setup(
    name="codex-router",
    version="0.1.0",
    description="Local-first Codex-only OpenAI-compatible gateway",
    package_dir={"": "src"},
    packages=find_packages("src"),
    python_requires=">=3.8",
    entry_points={"console_scripts": ["codex-router=codex_router.__main__:main"]},
)
