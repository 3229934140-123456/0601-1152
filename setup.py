from setuptools import setup, find_packages

setup(
    name="apptest-cli",
    version="1.0.0",
    description="移动 App 自动化测试平台命令行工具",
    author="QA Team",
    packages=find_packages(),
    include_package_data=True,
    package_data={
        "apptest": ["templates/*.html"],
    },
    install_requires=[
        "click>=8.1.0",
        "pyyaml>=6.0",
        "rich>=13.0.0",
        "jinja2>=3.1.0",
        "python-dateutil>=2.8.2",
        "tabulate>=0.9.0",
    ],
    entry_points={
        "console_scripts": [
            "apptest=apptest.cli:main",
        ],
    },
    python_requires=">=3.8",
)
