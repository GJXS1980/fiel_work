#!/usr/bin/python
# -*- coding: UTF-8 -*-
'''
Modbus Simu App
===============
'''
import click
import sys
import __builtin__


@click.command()
@click.option("-p", is_flag=True, help="use pymodbus as modbus backend")
def _run(p):
    __builtin__.USE_PYMODBUS = p
    if "-p" in sys.argv:
        # cleanup before kivy gets confused
        sys.argv.remove("-p")
    from ZPX.ui.gui import run
    run()


if __name__ == "__main__":
    _run()
