#!/usr/bin/python
# -*- coding: UTF-8 -*-

'''
Modbus Simu App
===============
'''
import kivy
kivy.require('1.4.2')
from kivy.app import App
from kivy.properties import ObjectProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.animation import Animation
from kivy.uix.textinput import TextInput
from kivy.uix.settings import SettingsWithSidebar
from kivy.uix.listview import ListView, ListItemButton
from kivy.adapters.listadapter import ListAdapter
from ZPX.utils.modbus import BLOCK_TYPES, configure_modbus_logger
from ZPX.ui.settings import SettingIntegerWithRange
from ZPX.utils.backgroundJob import BackgroundJob
import re
import os
import platform

from json import load, dump
from kivy.config import Config
from kivy.lang import Builder
import ZPX.ui.datamodel  #noqa
from pkg_resources import resource_filename
from serial.serialutil import SerialException

from distutils.version import LooseVersion

IS_DARWIN = platform.system().lower() == "darwin"
OSX_SIERRA = LooseVersion("10.12")
if IS_DARWIN:
    IS_HIGH_SIERRA_OR_ABOVE = LooseVersion(platform.mac_ver()[0])
else:
    IS_HIGH_SIERRA_OR_ABOVE = False

DEFAULT_SERIAL_PORT = '/dev/ptyp0' if not IS_HIGH_SIERRA_OR_ABOVE else '/dev/ttyp0'

if USE_PYMODBUS:
    from ZPX.utils.pymodbus_server import ModbusSimu
else:
    from ZPX.utils.modbus import ModbusSimu


MAP = {
    "Fun Code15": "Fun_Code15",
    'Fun Code02': 'Fun_Code02',
    'Fun Code16': 'Fun_Code16',
    'Fun Code03': 'Fun_Code03'
}
PARENT = __name__.split(".")[0]
settings_icon = resource_filename(PARENT, "assets/control.png")
app_icon = resource_filename(PARENT, "assets/logo.png")
modbus_template = resource_filename(PARENT, "templates/modbussimu.kv")
Builder.load_file(modbus_template)

SLAVES_FILE = resource_filename(__name__, "slaves.json")


class FloatInput(TextInput):
    pat2 = re.compile(r'\d+(?:,\d+)?')
    pat = re.compile('[^0-9]')

    def insert_text(self, substring, from_undo=False):
        pat = self.pat
        if '.' in self.text:
            s = re.sub(pat, '', substring)
        else:
            s = '.'.join([re.sub(pat, '', s) for s in substring.split('.', 1)])
        return super(FloatInput, self).insert_text(s, from_undo=from_undo)


class Gui(BoxLayout):
    """
    Gui of widgets. This is the root widget of the app.
    """

    # ---------------------GUI------------------------ #
    # Checkbox to select between tcp/serial
    interfaces = ObjectProperty()

    tcp = ObjectProperty()
    serial = ObjectProperty()

    # Boxlayout to hold interface settings
    interface_settings = ObjectProperty()

    # TCP port
    port = ObjectProperty()

    # Toggle button to start/stop modbus server
    start_stop_server = ObjectProperty()

    # Container for slave list
    slave_pane = ObjectProperty()
    # slave start address textbox
    slave_start_add = ObjectProperty()
    # slave end address textbox
    slave_end_add = ObjectProperty()
    # Slave device count text box
    slave_count = ObjectProperty()
    # Slave list
    slave_list = ObjectProperty()

    # Container for modbus data models
    data_model_loc = ObjectProperty()
    # Tabbed panel to hold various modbus datamodels
    data_models = ObjectProperty()

    # Data models
    data_count = ObjectProperty()
    data_model_Fun_Code15 = ObjectProperty()
    data_model_Fun_Code02 = ObjectProperty()
    data_model_Fun_Code16 = ObjectProperty()
    data_model_Fun_Code03 = ObjectProperty()

    settings = ObjectProperty()
    riptide_logo = ObjectProperty()

    reset_sim_btn = ObjectProperty()

    # Helpers
    # slaves = ["%s" %i for i in xrange(1, 248)]
    _data_map = {"tcp": {}, "rtu": {}}
    active_slave = None
    server_running = False
    simulating = False
    simu_time_interval = None
    anim = None
    restart_simu = False
    sync_modbus_thread = None
    sync_modbus_time_interval = 5
    _modbus_device = {"tcp": None, 'rtu': None}
    _slaves = {"tcp": None, "rtu": None}

    last_active_port = {"tcp": "", "serial": ""}
    active_server = "tcp"
    _serial_settings_changed = False

    def __init__(self, **kwargs):
        super(Gui, self).__init__(**kwargs)
        time_interval = kwargs.get("time_interval", 1)
        self.settings.icon = settings_icon
        self.riptide_logo.app_icon = app_icon
        self.config = Config.get_configparser('app')
        self.slave_list.adapter.bind(on_selection_change=self.select_slave)
        self.data_model_loc.disabled = True
        self.slave_pane.disabled = True
        self._init_Fun_Code15()
        self._init_registers()
        self._register_config_change_callback(
            self._update_serial_connection,
            'Modbus Serial'
        )
        self.data_model_loc.disabled = True
        cfg = {
            'no_modbus_log': not bool(eval(
                self.config.get("Logging", "logging"))),
            'no_modbus_console_log': not bool(
                eval(self.config.get("Logging", "console logging"))),
            'modbus_console_log_level': self.config.get("Logging",
                                                        "console log level"),
            'modbus_file_log_level': self.config.get("Logging",
                                                     "file log level"),
            'no_modbus_file_log': not bool(eval(
                self.config.get("Logging", "file logging"))),

            'modbus_log': kwargs['modbus_log']
        }
        mod_lib = "modbus_tk" if not USE_PYMODBUS else "pymodbus"
        configure_modbus_logger(cfg, protocol_logger=mod_lib)
        self.simu_time_interval = time_interval
        self.sync_modbus_thread = BackgroundJob(
            "modbus_sync",
            self.sync_modbus_time_interval,
            self._sync_modbus_block_values
        )
        self.sync_modbus_thread.start()
        self._slave_misc = {"tcp": [self.slave_start_add.text,
                                    self.slave_end_add.text,
                                    self.slave_count.text],
                            "rtu": [self.slave_start_add.text,
                                    self.slave_end_add.text,
                                    self.slave_count.text]}

    @property
    def modbus_device(self):
        return self._modbus_device[self.active_server]

    @modbus_device.setter
    def modbus_device(self, value):
        self._modbus_device[self.active_server] = value

    @property
    def slave(self):
        return self._slaves[self.active_server]

    @slave.setter
    def slave(self, value):
        self._slaves[self.active_server] = value

    @property
    def data_map(self):
        return self._data_map[self.active_server]

    @data_map.setter
    def data_map(self, value):
        self._data_map[self.active_server] = value

    def _init_Fun_Code15(self):
        time_interval = int(eval(self.config.get("Simulation",
                                                 "time interval")))
        minval = int(eval(self.config.get("Modbus Protocol",
                                          "bin min")))
        maxval = int(eval(self.config.get("Modbus Protocol",
                                          "bin max")))

        self.data_model_Fun_Code15.init(
            blockname="Fun_Code15",
            simulate=self.simulating,
            time_interval=time_interval,
            minval=minval,
            maxval=maxval,
            _parent=self
        )
        self.data_model_Fun_Code02.init(
            blockname="Fun_Code02",
            simulate=self.simulating,
            time_interval=time_interval,
            minval=minval,
            maxval=maxval,
            _parent=self
        )

    def _init_registers(self):
        time_interval = int(eval(self.config.get("Simulation",
                                                 "time interval")))
        minval = int(eval(self.config.get("Modbus Protocol",
                                          "reg min")))
        maxval = int(eval(self.config.get("Modbus Protocol",
                                          "reg max")))
        self.block_start = int(eval(self.config.get("Modbus Protocol",
                                                    "block start")))
        self.block_size = int(eval(self.config.get("Modbus Protocol",
                                                   "block size")))
        self.data_model_Fun_Code16.init(
            blockname="Fun_Code16",
            simulate=self.simulating,
            time_interval=time_interval,
            minval=minval,
            maxval=maxval,
            _parent=self
        )
        self.data_model_Fun_Code03.init(
            blockname="Fun_Code03",
            simulate=self.simulating,
            time_interval=time_interval,
            minval=minval,
            maxval=maxval,
            _parent=self
        )

    def _register_config_change_callback(self, callback, section, key=None):
        self.config.add_callback(callback, section, key)

    def _update_serial_connection(self, *args):
        self._serial_settings_changed = True

    def _create_modbus_device(self):
        kwargs = {}
        create_new = False
        if self.active_server == "rtu":

            kwargs["baudrate"] = int(eval(
                self.config.get('Modbus Serial', "baudrate")))
            kwargs["bytesize"] = int(eval(
                self.config.get('Modbus Serial', "bytesize")))
            kwargs["parity"] = self.config.get('Modbus Serial', "parity")
            kwargs["stopbits"] = int(eval(
                self.config.get('Modbus Serial', "stopbits")))
            kwargs["xonxoff"] = bool(eval(
                self.config.get('Modbus Serial', "xonxoff")))
            kwargs["rtscts"] = bool(eval(
                self.config.get('Modbus Serial', "rtscts")))
            kwargs["dsrdtr"] = bool(eval(
                self.config.get('Modbus Serial', "dsrdtr")))
            kwargs["writetimeout"] = int(eval(
                self.config.get('Modbus Serial', "writetimeout")))
            kwargs["timeout"] = bool(eval(
                self.config.get('Modbus Serial', "timeout")))
        elif self.active_server == 'tcp':
            kwargs['address'] = self.config.get('Modbus Tcp', 'ip')
        if not self.modbus_device:
            create_new = True
        else:
            if self.modbus_device.server_type == self.active_server:

                if str(self.modbus_device.port) != str(self.port.text):
                    create_new = True
                if self._serial_settings_changed:
                    create_new = True
            else:
                create_new = True
        if create_new:

            self.modbus_device = ModbusSimu(server=self.active_server,
                                            port=self.port.text,
                                            **kwargs
                                            )
            if self.slave is None:

                adapter = ListAdapter(
                        data=[],
                        cls=ListItemButton,
                        selection_mode='single'
                )
                self.slave = ListView(adapter=adapter)

            self._serial_settings_changed = False
        elif self.active_server == "rtu":
            if not USE_PYMODBUS:
                self.modbus_device._serial.open()

    def start_server(self, btn):
        if btn.state == "down":
            try:
                self._start_server()
            except SerialException as e:
                btn.state = "normal"
                self.show_error("Error in opening Serial port: %s" % e)
                return
            btn.text = "Stop"
        else:
            self._stop_server()
            btn.text = "Start"

    def _start_server(self):
        self._create_modbus_device()

        self.modbus_device.start()
        self.server_running = True
        self.interface_settings.disabled = True
        self.interfaces.disabled = True
        self.slave_pane.disabled = False
        if len(self.slave_list.adapter.selection):
            self.data_model_loc.disabled = False
            if self.simulating:
                self._simulate()

    def _stop_server(self):
        self.simulating = False
        self._simulate()
        self.modbus_device.stop()
        self.server_running = False
        self.interface_settings.disabled = False
        self.interfaces.disabled = False
        self.slave_pane.disabled = True
        self.data_model_loc.disabled = True

    def update_tcp_connection_info(self, checkbox, value):
        self.active_server = "tcp"
        if value:
            self.interface_settings.current = checkbox
            if self.last_active_port['tcp'] == "":
                self.last_active_port['tcp'] = 5440
            self.port.text = self.last_active_port['tcp']
            self._restore()
        else:
            self.last_active_port['tcp'] = self.port.text
            self._backup()

    def update_serial_connection_info(self, checkbox, value):
        self.active_server = "rtu"
        if value:
            self.interface_settings.current = checkbox
            if self.last_active_port['serial'] == "":
                self.last_active_port['serial'] = DEFAULT_SERIAL_PORT
            self.port.text = self.last_active_port['serial']
            self._restore()
        else:
            self.last_active_port['serial'] = self.port.text
            self._backup()

    def show_error(self, e):
        self.info_label.text = str(e)
        self.anim = Animation(top=190.0, opacity=1, d=2, t='in_back') +\
            Animation(top=190.0, d=3) +\
            Animation(top=0, opacity=0, d=2)
        self.anim.start(self.info_label)

    def add_slaves(self, *args):
        selected = self.slave_list.adapter.selection
        data = self.slave_list.adapter.data
        ret = self._process_slave_data(data)
        self._add_slaves(selected, data, ret)

    def _add_slaves(self, selected, data, ret):
        if ret[0]:
            start_slave_add, slave_count = ret[1:]
        else:
            return

        for slave_to_add in xrange(start_slave_add,
                                   start_slave_add + slave_count):
            if str(slave_to_add) in self.data_map:
                return
            self.data_map[str(slave_to_add)] = {
                "Fun_Code15": {
                    'data': {},
                    'item_strings': [],
                    "instance": self.data_model_Fun_Code15,
                    "dirty": False
                },
                "Fun_Code02": {
                    'data': {},
                    'item_strings': [],
                    "instance": self.data_model_Fun_Code02,
                    "dirty": False
                },
                "Fun_Code16": {
                    'data': {},
                    'item_strings': [],
                    "instance": self.data_model_Fun_Code16,
                    "dirty": False
                },
                "Fun_Code03": {
                    'data': {},
                    'item_strings': [],
                    "instance": self.data_model_Fun_Code03,
                    "dirty": False
                }
            }
            self.modbus_device.add_slave(slave_to_add)
            for block_name, block_type in BLOCK_TYPES.items():
                self.modbus_device.add_block(slave_to_add,
                                             block_name, block_type, self.block_start, self.block_size)

            data.append(str(slave_to_add))
        self.slave_list.adapter.data = data
        self.slave_list._trigger_reset_populate()

        for item in selected:
            index = self.slave_list.adapter.data.index(item.text)
            if not self.slave_list.adapter.get_view(index).is_selected:
                self.slave_list.adapter.get_view(index).trigger_action(
                    duration=0
                )
        self.slave_start_add.text = str(start_slave_add + slave_count)
        self.slave_end_add.text = self.slave_start_add.text
        self.slave_count.text = "1"

    def _process_slave_data(self, data):
        success = True
        data = sorted(data, key=int)
        # last_slave = 1 if not len(data) else data[-1]
        starting_address = int(self.slave_start_add.text)
        end_address = int(self.slave_end_add.text)
        if end_address < starting_address:
            end_address = starting_address
        try:
            slave_count = int(self.slave_count.text)
        except ValueError:
            slave_count = 1

        if str(starting_address) in data:
            self.show_error("slave already present (%s)" % starting_address)
            success = False
            return [success]
        if starting_address < 1:
            self.show_error("slave address (%s)"
                            " should be greater than 0 "% starting_address)
            success = False
            return [success]
        if starting_address > 247:
            self.show_error("slave address (%s)"
                            " beyond supported modbus slave "
                            "device address (247)" % starting_address)
            success = False
            return [success]

        size = (end_address - starting_address) + 1
        size = slave_count if slave_count > size else size

        if (size + starting_address) > 247:
            self.show_error("address range (%s) beyond "
                            "allowed modbus slave "
                            "devices(247)" % (size + starting_address))
            success = False
            return [success]
        self.slave_end_add.text = str(starting_address + size - 1)
        self.slave_count.text = str(size)
        return success, starting_address, size

    def delete_slaves(self, *args):
        selected = self.slave_list.adapter.selection
        slave = self.active_slave
        ct = self.data_models.current_tab
        for item in selected:
            self.modbus_device.remove_slave(int(item.text))
            self.slave_list.adapter.data.remove(item.text)
            self.slave_list._trigger_reset_populate()
            ct.content.clear_widgets(make_dirty=True)
            if self.simulating:
                self.simulating = False
                self.restart_simu = True
                self._simulate()
            self.data_map.pop(slave)

    def update_data_models(self, *args):
        active = self.active_slave
        tab = self.data_models.current_tab
        count = self.data_count.text
        self._update_data_models(active, tab, count, 1)

    def _update_data_models(self, active, tab, count, value):
        ct = tab
        current_tab = MAP[ct.text]

        ct.content.update_view()
        # self.data_map[self.active_slave][current_tab]['dirty'] = False
        _data = self.data_map[active][current_tab]
        item_strings = _data['item_strings']
        for i in xrange(int(count)):
            if len(item_strings) < self.block_size:
                _value = 1 if isinstance(value, int) else value[i]
                updated_data, item_strings = ct.content.add_data(_value, item_strings)
                _data['data'].update(updated_data)
                _data['item_strings'] = item_strings
                for k, v in updated_data.iteritems():
                    self.modbus_device.set_values(int(active),
                                                  current_tab, k, v)
            else:
                msg = ("OutOfModbusBlockError: address %s"
                       " is out of block size %s" % (len(item_strings),
                                                     self.block_size))
                self.show_error(msg)
                break

    def sync_data_callback(self, blockname, data):
        ct = self.data_models.current_tab
        current_tab = MAP[ct.text]
        if blockname != current_tab:
            current_tab = blockname
        try:
            _data = self.data_map[self.active_slave][current_tab]
            _data['data'].update(data)
            for k, v in data.iteritems():
                self.modbus_device.set_values(int(self.active_slave),
                                              current_tab, k, int(v))
        except KeyError:
            pass

    def delete_data_entry(self, *args):
        ct = self.data_models.current_tab
        current_tab = MAP[ct.text]
        _data = self.data_map[self.active_slave][current_tab]
        item_strings = _data['item_strings']
        deleted, data = ct.content.delete_data(item_strings)
        dm = _data['data']
        for index in deleted:
            dm.pop(index, None)

        if deleted:
            self.update_backend(int(self.active_slave), current_tab, data)
            msg = ("Deleting "
               "individual modbus register/discrete_inputs/Fun_Code15 is not supported."
               "The data is removed from GUI and the corresponding value is"
               "updated to '0' in backend . ")
            self.show_error(msg)

    def select_slave(self, adapter):
        ct = self.data_models.current_tab
        if len(adapter.selection) != 1:
            # Multiple selection - No Data Update
            ct.content.clear_widgets(make_dirty=True)
            if self.simulating:
                self.simulating = False
                self.restart_simu = True
                self._simulate()
            self.data_model_loc.disabled = True
            self.active_slave = None

        else:
            self.data_model_loc.disabled = False
            if self.restart_simu:
                self.simulating = True
                self.restart_simu = False
                self._simulate()
            self.active_slave = self.slave_list.adapter.selection[0].text
            self.refresh()

    def refresh(self):
        for child in self.data_models.tab_list:
            dm = self.data_map[self.active_slave][MAP[child.text]]['data']
            child.content.refresh(dm)

    def update_backend(self, slave_id, blockname, new_data, ):
        self.modbus_device.remove_block(slave_id, blockname)
        self.modbus_device.add_block(slave_id, blockname,
                                     BLOCK_TYPES[blockname], 0,
                                     self.block_size)
        for k, v in new_data.iteritems():
            self.modbus_device.set_values(slave_id, blockname, k, int(v))

    def change_simulation_settings(self, **kwargs):
        self.data_model_Fun_Code15.reinit(**kwargs)
        self.data_model_Fun_Code02.reinit(**kwargs)
        self.data_model_Fun_Code16.reinit(**kwargs)
        self.data_model_Fun_Code03.reinit(**kwargs)

    def change_datamodel_settings(self, key, value):
        if "max" in key:
            data = {"maxval": int(value)}
        else:
            data = {"minval": int(value)}

        if "bin" in key:
            self.data_model_Fun_Code15.reinit(**data)
            self.data_model_Fun_Code02.reinit(**data)
        else:
            self.data_model_Fun_Code16.reinit(**data)
            self.data_model_Fun_Code03.reinit(**data)

    def start_stop_simulation(self, btn):
        if btn.state == "down":
            self.simulating = True
            self.reset_sim_btn.disabled = True
        else:
            self.simulating = False
            self.reset_sim_btn.disabled = False
            if self.restart_simu:
                self.restart_simu = False
        self._simulate()

    def _simulate(self):
        self.data_model_Fun_Code15.start_stop_simulation(self.simulating)
        self.data_model_Fun_Code02.start_stop_simulation(self.simulating)
        self.data_model_Fun_Code16.start_stop_simulation(self.simulating)
        self.data_model_Fun_Code03.start_stop_simulation(
            self.simulating)

    def reset_simulation(self, *args):
        if not self.simulating:
            self.data_model_Fun_Code15.reset_block_values()
            self.data_model_Fun_Code02.reset_block_values()
            self.data_model_Fun_Code16.reset_block_values()
            self.data_model_Fun_Code03.reset_block_values()

    def _sync_modbus_block_values(self):
        """
        track external changes in modbus block values and sync GUI
        ToDo:
        A better way to update GUI when simulation is on going  !!
        """
        if not self.simulating:
            if self.active_slave:
                _data_map = self.data_map[self.active_slave]
                for block_name, value in _data_map.items():
                    updated = {}
                    for k, v in value['data'].items():
                        actual_data = self.modbus_device.get_values(
                            int(self.active_slave),
                            block_name,
                            int(k),

                        )
                        try:
                            if actual_data[0] != int(v):
                                updated[k] = actual_data[0]
                        except TypeError:
                            pass
                    if updated:
                        value['data'].update(updated)
                        self.refresh()

    def _backup(self):
        if self.slave is not None:
            self.slave.adapter.data = self.slave_list.adapter.data
        self._slave_misc[self.active_server] = [
            self.slave_start_add.text,
            self.slave_end_add.text,
            self.slave_count.text
        ]

    def _restore(self):
        if self.slave is None:

            adapter = ListAdapter(
                    data=[],
                    cls=ListItemButton,
                    selection_mode='single'
            )
            self.slave = ListView(adapter=adapter)
        self.slave_list.adapter.data = self.slave.adapter.data
        (self.slave_start_add.text,
         self.slave_end_add.text,
         self.slave_count.text) = self._slave_misc[self.active_server]
        self.slave_list._trigger_reset_populate()

    def save_state(self):
        with open(SLAVES_FILE, 'w') as f:
            slave = [int(slave_no) for slave_no in self.slave_list.adapter.data]
            slaves_memory = []
            for slaves, mem in self.data_map.iteritems():
                for name, value in mem.iteritems():
                    if len(value['data']) != 0:
                        slaves_memory.append((slaves, name, map(int, value['data'].values())))

            dump(dict(
                slaves_list=slave, active_server=self.active_server,
                port=self.port.text, slaves_memory=slaves_memory
            ), f, indent=4)

    def load_state(self):
        if not bool(eval(self.config.get("State", "load state"))) or \
                not os.path.isfile(SLAVES_FILE):
            return

        with open(SLAVES_FILE, 'r') as f:
            try:
                data = load(f)
            except ValueError as e:
                self.show_error(
                    "LoadError: Failed to load previous simulation state : %s "
                    % e.message
                )
                return

            if 'active_server' not in data or 'port' not in data \
                    or 'slaves_list' not in data or 'slaves_memory' not in data:
                self.show_error("LoadError: Failed to load previous simulation state : JSON Key "
                                "Missing")
                return

            slaves_list = data['slaves_list']
            if not len(slaves_list):
                return

            if data['active_server'] == 'tcp':
                self.tcp.active = True
                self.serial.active = False
                self.interface_settings.current = self.tcp
            else:
                self.tcp.active = False
                self.serial.active = True
                self.interface_settings.current = self.serial

            self.active_server = data['active_server']
            self.port.text = data['port']

            self._create_modbus_device()

            start_slave = 0
            temp_list = []
            slave_count = 1
            for first, second in zip(slaves_list[:-1], slaves_list[1:]):
                if first+1 == second:
                    slave_count += 1
                else:
                    temp_list.append((slaves_list[start_slave], slave_count))
                    start_slave += slave_count
                    slave_count = 1
            temp_list.append((slaves_list[start_slave], slave_count))

            for start_slave, slave_count in temp_list:
                self._add_slaves(
                    self.slave_list.adapter.selection,
                    self.slave_list.adapter.data,
                    (True, start_slave, slave_count)
                )

            memory_map = {
                'Fun_Code15': self.data_models.tab_list[3],
                'Fun_Code02': self.data_models.tab_list[2],
                'Fun_Code16': self.data_models.tab_list[1],
                'Fun_Code03': self.data_models.tab_list[0]
            }
            slaves_memory = data['slaves_memory']
            for slave_memory in slaves_memory:
                active_slave, memory_type, memory_data = slave_memory
                self._update_data_models(active_slave, memory_map[memory_type], len(memory_data), memory_data)


#!/usr/bin/python
# -*- coding: UTF-8 -*-


setting_panel = """
[
  {
    "type": "title",
    "title": "Modbus TCP Settings"
  },
  {
    "type": "string",
    "title": "IP",
    "desc": "Modbus Server IP address",
    "section": "Modbus Tcp",
    "key": "IP"
  },
  {
    "type": "title",
    "title": "Modbus Serial Settings"
  },
  {
    "type": "numeric",
    "title": "baudrate",
    "desc": "Modbus Serial baudrate",
    "section": "Modbus Serial",
    "key": "baudrate"
  },
  {
    "type": "options",
    "title": "bytesize",
    "desc": "Modbus Serial bytesize",
    "section": "Modbus Serial",
    "key": "bytesize",
    "options": ["5", "6", "7", "8"]

  },
  {
    "type": "options",
    "title": "parity",
    "desc": "Modbus Serial parity",
    "section": "Modbus Serial",
    "key": "parity",
    "options": ["N", "E", "O", "M", "S"]
  },
  {
    "type": "options",
    "title": "stopbits",
    "desc": "Modbus Serial stopbits",
    "section": "Modbus Serial",
    "key": "stopbits",
    "options": ["1", "1.5", "2"]

  },
  {
    "type": "bool",
    "title": "xonxoff",
    "desc": "Modbus Serial xonxoff",
    "section": "Modbus Serial",
    "key": "xonxoff"
  },
  {
    "type": "bool",
    "title": "rtscts",
    "desc": "Modbus Serial rtscts",
    "section": "Modbus Serial",
    "key": "rtscts"
  },
  {
    "type": "bool",
    "title": "dsrdtr",
    "desc": "Modbus Serial dsrdtr",
    "section": "Modbus Serial",
    "key": "dsrdtr"
  },
  {
    "type": "numeric",
    "title": "timeout",
    "desc": "Modbus Serial timeout",
    "section": "Modbus Serial",
    "key": "timeout"
  },
  {
    "type": "numeric",
    "title": "write timeout",
    "desc": "Modbus Serial write timeout",
    "section": "Modbus Serial",
    "key": "writetimeout"
  },
  {
    "type": "title",
    "title": "Modbus Protocol Settings"
  },
  {
    "type": "numeric",
    "title": "Block Start",
    "desc": "Modbus Block Start index",
    "section": "Modbus Protocol",
    "key": "Block Start"
  },
  { "type": "numeric",
    "title": "Block Size",
    "desc": "Modbus Block Size for various registers/Fun_Code15/inputs",
    "section": "Modbus Protocol",
    "key": "Block Size"
  },
  {
    "type": "numeric_range",
    "title": "Coil/Discrete Input MinValue",
    "desc": "Minimum value a coil/discrete input can hold (0).An invalid value will be discarded unless Override flag is set",
    "section": "Modbus Protocol",
    "key": "bin min",
    "range": [0,0]
  },
  {
    "type": "numeric_range",
    "title": "Coil/Discrete Input MaxValue",
    "desc": "Maximum value a coil/discrete input can hold (1). An invalid value will be discarded unless Override flag is set",
    "section": "Modbus Protocol",
    "key": "bin max",
    "range": [1,1]

  },
  {
    "type": "numeric_range",
    "title": "Holding/Input register MinValue",
    "desc": "Minimum value a registers can hold (0).An invalid value will be discarded unless Override flag is set",
    "section": "Modbus Protocol",
    "key": "reg min",
    "range": [0,65535]
  },
  {
    "type": "numeric_range",
    "title": "Holding/Input register MaxValue",
    "desc": "Maximum value a register input can hold (65535). An invalid value will be discarded unless Override flag is set",
    "section": "Modbus Protocol",
    "key": "reg max",
    "range": [0,65535]
  },
  {
    "type": "title",
    "title": "Logging"
  },
  { "type": "bool",
    "title": "Modbus Master Logging Control",
    "desc": " Enable/Disable Modbus Logging (console/file)",
    "section": "Logging",
    "key": "logging"
  },
  { "type": "bool",
    "title": "Modbus Console Logging",
    "desc": " Enable/Disable Modbus Console Logging",
    "section": "Logging",
    "key": "console logging"
  },
  {
    "type": "options",
    "title": "Modbus console log levels",
    "desc": "Log levels for modbus_tk",
    "section": "Logging",
    "key": "console log level",
    "options": ["INFO", "WARNING", "DEBUG", "CRITICAL"]
  },
  { "type": "bool",
    "title": "Modbus File Logging",
    "desc": " Enable/Disable Modbus File Logging",
    "section": "Logging",
    "key": "file logging"
  },
  {
    "type": "options",
    "title": "Modbus file log levels",
    "desc": "file Log levels for modbus_tk",
    "section": "Logging",
    "key": "file log level",
    "options": ["INFO", "WARNING", "DEBUG", "CRITICAL"]
  },

  {
    "type": "path",
    "title": "Modbus log file",
    "desc": "Modbus log file (changes takes place only after next start of app)",
    "section": "Logging",
    "key": "log file"
  },
  {
    "type": "title",
    "title": "Simulation"
  },
  {
    "type": "numeric",
    "title": "Time interval",
    "desc": "When simulation is enabled, data is changed for every 'n' seconds defined here",
    "section": "Simulation",
    "key": "time interval"
  },
  {
    "type": "title",
    "title": "State"
  },
  {
    "type": "bool",
    "title": "Load State",
    "desc": "Whether the previous state should be loaded or not, if not the original state is loaded",
    "section": "State",
    "key": "load state"
  }

]
"""


class ModbusSimuApp(App):
    '''The kivy App that runs the main root. All we do is build a Gui
    widget into the root.'''
    gui = None
    title = "Modbus Simulator"
    settings_cls = None
    use_kivy_settings = True
    settings_cls = SettingsWithSidebar

    def build(self):
        self.gui = Gui(
            modbus_log=os.path.join(self.user_data_dir, 'modbus.log')
        )
        self.gui.load_state()
        return self.gui

    def on_pause(self):
        return True

    def on_stop(self):
        if self.gui.server_running:
            if self.gui.simulating:
                self.gui.simulating = False
                self.gui._simulate()
            self.gui.modbus_device.stop()
        self.gui.sync_modbus_thread.cancel()
        self.config.write()
        self.gui.save_state()

    def show_settings(self, btn):
        self.open_settings()

    def build_config(self, config):
        config.add_section('Modbus Tcp')
        config.add_section('Modbus Protocol')
        config.add_section('Modbus Serial')
        config.set('Modbus Tcp', "ip", '127.0.0.1')
        config.set('Modbus Protocol', "block start", 0)
        config.set('Modbus Protocol', "block size", 100)
        config.set('Modbus Protocol', "bin min", 0)
        config.set('Modbus Protocol', "bin max", 1)
        config.set('Modbus Protocol', "reg min", 0)
        config.set('Modbus Protocol', "reg max", 65535)
        config.set('Modbus Serial', "baudrate", 9600)
        config.set('Modbus Serial', "bytesize", "8")
        config.set('Modbus Serial', "parity", 'N')
        config.set('Modbus Serial', "stopbits", "1")
        config.set('Modbus Serial', "xonxoff", 0)
        config.set('Modbus Serial', "rtscts", 0)
        config.set('Modbus Serial', "dsrdtr", 0)
        config.set('Modbus Serial', "writetimeout", 2)
        config.set('Modbus Serial', "timeout", 2)

        config.add_section('Logging')
        config.set('Logging', "log file",  os.path.join(self.user_data_dir,
                                                        'modbus.log'))

        config.set('Logging', "logging", 1)
        config.set('Logging', "console logging", 1)
        config.set('Logging', "console log level", "DEBUG")
        config.set('Logging', "file log level", "DEBUG")
        config.set('Logging', "file logging", 1)

        config.add_section('Simulation')
        config.set('Simulation', 'time interval', 1)

        config.add_section('State')
        config.set('State', 'load state', 1)

    def build_settings(self, settings):
        settings.register_type("numeric_range", SettingIntegerWithRange)
        settings.add_json_panel('Modbus Settings', self.config,
                                data=setting_panel
                                )

    def on_config_change(self, config, section, key, value):
        if config is not self.config:
            return
        token = section, key
        if token == ("Simulation", "time interval"):
            self.gui.change_simulation_settings(time_interval=eval(value))
        if section == "Modbus Protocol" and key in ("bin max",
                                           "bin min", "reg max",
                                           "reg min", "override"):
            self.gui.change_datamodel_settings(key, value)
        if section == "Modbus Protocol" and key == "block start":
            self.gui.block_start = int(value)
        if section == "Modbus Protocol" and key == "block size":
            self.gui.block_size = int(value)

    def close_settings(self, *args):
        super(ModbusSimuApp, self).close_settings()


def run():
    ModbusSimuApp().run()
