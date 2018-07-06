from setuptools import setup, find_packages
from setuptools.command.install import install
import sys
from ZPX.version import __VERSION__


def install_requires():
    with open('requirements') as reqs:
        install_req = [
            line for line in reqs.read().split('\n')
        ]
    return install_req


def readme():
    with open("README.md") as f:
        return f.read()

setup(
    name="ZPX",
    url="https://github.com/riptideio/modbus-simulator.git",
    description="Modbus Simulator uing Kivy, Pymodbus, Modbus-tk",
    version=__VERSION__,
    long_description=readme(),
    keywords="Modbus Simulator",
    author="3215000926ZPX",
    packages=find_packages(),
    install_requires=install_requires(),
    entry_points={
        'console_scripts': [
            'modbus.simu = ZPX.main:_run',
        ],
    },
    include_package_data=True
)
