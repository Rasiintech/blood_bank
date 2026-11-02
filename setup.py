from setuptools import find_packages, setup

with open("requirements.txt") as f:
	install_requires = [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]

# get version from __version__ variable in blood_bank/__init__.py
from blood_bank import __version__ as version

setup(
	name="blood_bank",
	version=version,
	description="Blood bank and transfusion management for Frappe Healthcare v14",
	author="Cibaar Technologies",
	author_email="cibaartechnologies@gmail.com",
	packages=find_packages(),
	zip_safe=False,
	include_package_data=True,
	install_requires=install_requires,
)
