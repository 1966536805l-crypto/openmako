from setuptools import find_packages, setup


setup(
    name="open-mako",
    version="0.1.0",
    description="A local-first auditable agent runtime for coding and data work.",
    python_requires=">=3.9",
    packages=find_packages(include=["quantagent", "quantagent.*"]),
    include_package_data=True,
    package_data={
        "quantagent": [
            "vendor/THIRD_PARTY_NOTICES.md",
            "vendor/hermes/LICENSE",
            "vendor/hermes/skills/*/*/SKILL.md",
            "vendor/hermes/skills/*/*/references/*.md",
        ],
    },
    entry_points={"console_scripts": ["mako=quantagent.cli:main", "openmako=quantagent.cli:main", "qagent=quantagent.cli:main"]},
)
