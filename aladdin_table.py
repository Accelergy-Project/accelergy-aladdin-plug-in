# -*- coding: utf-8 -*-
import math
import sys
import os
import csv
from accelergy.helper_functions import (
    oneD_linear_interpolation,
    oneD_quadratic_interpolation,
)
from accelergy.plug_in_interface.estimator_wrapper import (
    SupportedComponent,
    PrintableCall,
)

from copy import deepcopy
from accelergy.plug_in_interface.interface import *

# in your metric, please set the accuracy you think Aladdin's estimations are
ALADDIN_ACCURACY = 70
# MIT License
#
# Copyright (c) 2019 Yannan (Nellie) Wu
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.


class AladdinTable(AccelergyPlugIn):
    # -------------------------------------------------------------------------------------
    # Interface functions, function name, input arguments, and output have to adhere
    # -------------------------------------------------------------------------------------
    def __init__(self):
        # example primitive classes supported by this estimator
        self.supported_pc = [
            "regfile",
            "SRAM",
            "counter",
            "comparator",
            "crossbar",
            "wire",
            "FIFO",
            "bitwise",
            "intadder",
            "intmultiplier",
            "intmac",
            "fpadder",
            "fpmultiplier",
            "fpmac",
            "reg",
        ]
        self.aladdin_area_query_plug_ins = AladdinAreaQueires(self.supported_pc)

    def get_name(self) -> str:
        return "Aladdin_table"

    def primitive_action_supported(self, query: AccelergyQuery) -> AccuracyEstimation:
        class_name = query.class_name
        attributes = query.class_attrs
        action_name = query.action_name
        arguments = query.action_args
        # Legacy interface dictionary has keys class_name, attributes, action_name, and arguments
        interface = query.to_legacy_interface_dict()

        assert "technology" in attributes, "No technology specified in the request."
        technology = attributes["technology"]
        if class_name not in self.supported_pc:
            self.logger.info(
                f"Primitive class {class_name} is not supported. Supported classes are: {self.supported_pc}"
            )
            return AccuracyEstimation(0)
        SUPPORTED_TECH = [40, "40", "40nm", 45, "45", "45nm"]
        if technology not in SUPPORTED_TECH:
            self.logger.info(
                f"Technology {technology} is not supported. Supported technologies are: {SUPPORTED_TECH}"
            )
            return AccuracyEstimation(0)

        if class_name == "SRAM":
            width = attributes["width"]
            depth = attributes["depth"]
            if depth <= 128 and width <= 32:
                return AccuracyEstimation(ALADDIN_ACCURACY)
            else:
                self.logger.info(
                    "Only SRAMs with depth <= 128 and width <= 32 are supported by Aladdin"
                )
                return AccuracyEstimation(0)

        return AccuracyEstimation(ALADDIN_ACCURACY)

    def estimate_energy(self, query: AccelergyQuery) -> Estimation:
        class_name = query.class_name
        if "width" not in query.class_attrs and "width" in query.class_attrs:
            query.class_attrs["width"] = query.class_attrs["width"]
        # Legacy interface dictionary has keys class_name, attributes, action_name, and arguments
        interface = query.to_legacy_interface_dict()

        query_function_name = class_name + "_estimate_energy"
        energy = getattr(self, query_function_name)(interface)
        return Estimation(energy, "p")  # energy is in pJ

    def primitive_area_supported(self, query: AccelergyQuery) -> AccuracyEstimation:
        class_name = query.class_name
        if "width" not in query.class_attrs and "width" in query.class_attrs:
            query.class_attrs["width"] = query.class_attrs["width"]
        # Legacy interface dictionary has keys class_name, attributes, action_name, and arguments
        interface = query.to_legacy_interface_dict()

        assert (
            "technology" in interface["attributes"]
        ), "No technology specified in the request."
        class_name = interface["class_name"]
        technology = interface["attributes"]["technology"]
        if (
            technology == 40
            or technology == "40"
            or technology == "40nm"
            or technology == 45
            or technology == "45"
            or technology == "45nm"
        ) and class_name in self.supported_pc:

            # small SRAM can be approximated as regfile
            if class_name == "SRAM":
                width = interface["attributes"]["width"]
                depth = interface["attributes"]["depth"]
                if depth <= 128 and width <= 16:
                    return AccuracyEstimation(ALADDIN_ACCURACY)
                else:
                    return AccuracyEstimation(0)

            return AccuracyEstimation(ALADDIN_ACCURACY)
        return AccuracyEstimation(0)  # if not supported, accuracy is 0

    def estimate_area(self, query: AccelergyQuery) -> Estimation:
        # Legacy interface dictionary has keys class_name, attributes, action_name, and arguments
        interface = query.to_legacy_interface_dict()
        area = self.aladdin_area_query_plug_ins.estimate_area(interface)
        return Estimation(area, "u^2")  # area is in um^2

    # ============================================================
    # User's functions, purely user-defined
    # ============================================================
    @staticmethod
    def query_csv_using_latency(interface, csv_file_path):
        # default latency for Aladdin estimation is
        global_cycle_seconds = interface["attributes"]["global_cycle_seconds"]
        latency = global_cycle_seconds * interface["arguments"]["action_latency_cycles"]
        # round to an existing latency (can perform linear interpolation as well)
        if isinstance(latency, str) and "ns" in latency:
            latency = math.ceil(float(latency.split("ns")[0]))
        elif isinstance(latency, str) and "ps" in latency:
            latency = math.ceil(float(latency.split("ps")[0]) / 1000)
        else:
            latency = math.ceil(latency)
        if latency > 10:
            latency = 10
        elif latency > 6:
            latency = 6
        # there are only two types of energy in Aladdin tables
        action_name = (
            "idle energy(pJ)"
            if interface["action_name"] == "leak"
            else "dynamic energy(pJ)"
        )
        with open(csv_file_path) as csv_file:
            reader = csv.DictReader(csv_file)
            rows = [row for row in reader]
            for row in rows:
                if row["latency(ns)"] == str(latency):
                    energy = float(row[action_name])
                    break
            else:
                energy = float(rows[0][action_name])
                latency = float(rows[0]["latency(ns)"])
        if interface["action_name"] == "leak":
            energy *= global_cycle_seconds / latency * 1e9
        return energy

    def SRAM_estimate_energy(self, interface):
        return self.regfile_estimate_energy(interface)

    def regfile_estimate_energy(self, interface):
        width = interface["attributes"]["width"]
        depth = interface["attributes"]["depth"]
        this_dir, this_filename = os.path.split(__file__)
        csv_file_path = os.path.join(this_dir, "data/reg.csv")
        if depth == 0:
            return 0
        action_name = interface["action_name"]

        if action_name == "leak":
            reg_interface = deepcopy(interface)
            reg_energy = AladdinTable.query_csv_using_latency(
                reg_interface, csv_file_path
            )
            comparator_interface = {
                "name": "comparator",
                "attributes": {
                    **interface["attributes"],
                    **{"width": math.ceil(math.log2(float(depth)))},
                },
                "action_name": "leak",
                "arguments": interface["arguments"],
            }
            comparator_energy = self.comparator_estimate_energy(comparator_interface)
        else:

            if interface["arguments"] is not None:
                data_delta = interface["arguments"].get("data_delta", 1)
            else:
                data_delta = 1

            if interface["arguments"] is not None:
                address_delta = interface["arguments"].get("address_delta", 1)
            else:
                address_delta = 1

            reg_interface = deepcopy(interface)
            if data_delta == 0:
                reg_energy = 0
            else:
                reg_energy = AladdinTable.query_csv_using_latency(
                    reg_interface, csv_file_path
                )
            if address_delta != 0:
                comp_action = action_name
                comparator_interface = {
                    "name": "comparator",
                    "attributes": {
                        **interface["attributes"],
                        **{"width": math.ceil(math.log2(float(depth)))},
                    },
                    "action_name": comp_action,
                    "arguments": interface["arguments"],
                }
                comparator_energy = self.comparator_estimate_energy(
                    comparator_interface
                )
            else:
                comparator_energy = 0
        # register file access is naively modeled as vector access of registers
        reg_file_energy = reg_energy * width + comparator_energy * depth
        return reg_file_energy

    def reg_estimate_energy(self, interface):
        this_dir, this_filename = os.path.split(__file__)
        csv_file_path = os.path.join(this_dir, "data/reg.csv")
        reg_interface = deepcopy(interface)
        reg_energy = AladdinTable.query_csv_using_latency(reg_interface, csv_file_path)
        return reg_energy

    def FIFO_estimate_energy(self, interface):
        datawidth = interface["attributes"]["width"]
        depth = interface["attributes"]["depth"]
        if depth == 0:
            return 0
        this_dir, this_filename = os.path.split(__file__)
        csv_file_path = os.path.join(this_dir, "data/reg.csv")
        reg_energy = AladdinTable.query_csv_using_latency(interface, csv_file_path)

        if interface["action_name"] == "leak":
            action_name = "leak"
        else:
            action_name = "access"

        comparator_interface = {
            "attributes": {"width": math.log2(float(depth))},
            "action_name": action_name,
        }
        comparator_energy = self.comparator_estimate_energy(comparator_interface)
        energy = reg_energy * datawidth + comparator_energy
        return energy

    def crossbar_estimate_energy(self, interface):
        n_inputs = interface["attributes"]["n_inputs"]
        n_outputs = interface["attributes"]["n_outputs"]
        datawidth = interface["attributes"]["width"]
        this_dir, this_filename = os.path.split(__file__)
        csv_file_path = os.path.join(this_dir, "data/crossbar.csv")
        csv_energy = AladdinTable.query_csv_using_latency(interface, csv_file_path)
        crossbar_energy = csv_energy * n_inputs * (n_outputs / 4) * (datawidth / 32)
        return crossbar_energy

    def counter_estimate_energy(self, interface):
        width = interface["attributes"]["width"]
        this_dir, this_filename = os.path.split(__file__)
        csv_file_path = os.path.join(this_dir, "data/counter.csv")
        csv_energy = AladdinTable.query_csv_using_latency(interface, csv_file_path)
        energy = csv_energy * (width / 32)
        return energy

    def wire_estimate_energy(self, interface):
        action_name = interface["action_name"]
        if action_name == "transfer" or action_name == "transfer_random":
            len_str = str(interface["attributes"]["length"])
            if "m" not in len_str:
                length_um = float(len_str)
                self.logger.warn("No wire length unit provided, default to um")
            else:
                if "mm" in len_str:
                    length_um = float(len_str.split("mm")[0]) * 10**3
                elif "um" in len_str:
                    length_um = float(len_str.split("um")[0])
                elif "nm" in len_str:
                    length_um = float(len_str.split("nm")[0]) * 10**-3

                else:
                    self.logger.warn(
                        "Not recognizing the unit of the wire length, 0 energy"
                    )
                    length_um = 0

            datawidth = interface["attributes"]["width"]
            C_per_um = 1.627 * 10**-15  # F per um
            VDD = 1
            alpha = 0.2
            E_pJ = datawidth * alpha * C_per_um * length_um * VDD**2 * 10**12
            return E_pJ

        else:
            return 0

    def comparator_estimate_energy(self, interface):
        datawidth = interface["attributes"]["width"]
        this_dir, this_filename = os.path.split(__file__)
        csv_file_path = os.path.join(this_dir, "data/comparator.csv")
        csv_energy = AladdinTable.query_csv_using_latency(interface, csv_file_path)
        energy = csv_energy * (datawidth / 32)
        return energy

    def intmac_estimate_energy(self, interface):
        # mac is naively modeled as adder and multiplier
        multiplier_interface = deepcopy(interface)
        if interface["action_name"] == "mac_gated":
            multiplier_interface["action_name"] = "mult_gated"
        elif interface["action_name"] == "mac_reused":
            multiplier_interface["action_name"] = "mult_reused"
        elif interface["action_name"] == "leak":
            multiplier_interface["action_name"] = "leak"
        else:
            multiplier_interface["action_name"] = "mult_random"
        adder_energy = self.intadder_estimate_energy(interface)
        multiplier_energy = self.intmultiplier_estimate_energy(multiplier_interface)
        energy = adder_energy + multiplier_energy
        return energy

    def fpmac_estimate_energy(self, interface):
        # fpmac is naively modeled as fpadder and fpmultiplier
        multiplier_interface = deepcopy(interface)
        if interface["action_name"] == "mac_gated":
            multiplier_interface["action_name"] = "mult_gated"
        elif interface["action_name"] == "mac_reused":
            multiplier_interface["action_name"] = "mult_reused"
        elif interface["action_name"] == "leak":
            multiplier_interface["action_name"] = "leak"
        else:
            multiplier_interface["action_name"] = "mult_random"
        fpadder_energy = self.fpadder_estimate_energy(interface)
        fpmultiplier_energy = self.fpmultiplier_estimate_energy(interface)
        energy = fpadder_energy + fpmultiplier_energy
        return energy

    def intadder_estimate_energy(self, interface):
        this_dir, this_filename = os.path.split(__file__)
        nbit = interface["attributes"]["width"]
        csv_nbit = 32
        csv_file_path = os.path.join(this_dir, "data/adder.csv")
        energy = AladdinTable.query_csv_using_latency(interface, csv_file_path)
        if not nbit == csv_nbit:
            energy = oneD_linear_interpolation(
                nbit, [{"x": 0, "y": 0}, {"x": csv_nbit, "y": energy}]
            )
        return energy

    def fpadder_estimate_energy(self, interface):
        this_dir, this_filename = os.path.split(__file__)
        nbit_exponent = interface["attributes"]["exponent"]
        nbit_mantissa = interface["attributes"]["mantissa"]
        nbit = nbit_mantissa + nbit_exponent
        if nbit_exponent + nbit_mantissa <= 32:
            csv_nbit = 32
            csv_file_path = os.path.join(this_dir, "data/fp_sp_adder.csv")
        else:
            csv_nbit = 64
            csv_file_path = os.path.join(this_dir, "data/fp_dp_adder.csv")
        energy = AladdinTable.query_csv_using_latency(interface, csv_file_path)
        if not nbit == csv_nbit:
            energy = oneD_linear_interpolation(
                nbit, [{"x": 0, "y": 0}, {"x": csv_nbit, "y": energy}]
            )
        return energy

    def intmultiplier_estimate_energy(self, interface):
        this_dir, this_filename = os.path.split(__file__)
        nbit = interface["attributes"]["width"]
        action_name = interface["action_name"]
        if action_name == "mult_gated":
            # reflect gated multiplier energy
            interface["action_name"] = "leak"
        csv_nbit = 32
        csv_file_path = os.path.join(this_dir, "data/multiplier.csv")
        energy = AladdinTable.query_csv_using_latency(interface, csv_file_path)

        if not nbit == csv_nbit:
            energy = oneD_quadratic_interpolation(
                nbit, [{"x": 0, "y": 0}, {"x": csv_nbit, "y": energy}]
            )
        if action_name == "mult_reused":
            energy = 0.85 * energy
        return energy

    def fpmultiplier_estimate_energy(self, interface):
        this_dir, this_filename = os.path.split(__file__)
        action_name = interface["action_name"]
        if action_name == "mult_gated":
            # reflect gated multiplier energy
            interface["action_name"] = "leak"
        nbit_exponent = interface["attributes"]["exponent"]
        nbit_mantissa = interface["attributes"]["mantissa"]
        nbit = nbit_mantissa + nbit_exponent
        if nbit_exponent + nbit_mantissa <= 32:
            csv_nbit = 32
            csv_file_path = os.path.join(this_dir, "data/fp_sp_multiplier.csv")
        else:
            csv_nbit = 64
            csv_file_path = os.path.join(this_dir, "data/fp_dp_multiplier.csv")
        energy = AladdinTable.query_csv_using_latency(interface, csv_file_path)
        if not nbit == csv_nbit:
            energy = oneD_quadratic_interpolation(
                nbit, [{"x": 0, "y": 0}, {"x": csv_nbit, "y": energy}]
            )
        if action_name == "mult_reused":
            energy = 0.85 * energy
        return energy

    def bitwise_estimate_energy(self, interface):
        this_dir, this_filename = os.path.split(__file__)
        csv_file_path = os.path.join(this_dir, "data/bitwise.csv")
        csv_energy = AladdinTable.query_csv_using_latency(interface, csv_file_path)
        return csv_energy

    def get_supported_components(self) -> List[SupportedComponent]:
        components = {
            "regfile": (["width", "depth"], ["leak", "access"]),
            "SRAM": (["width", "depth"], ["leak", "access"]),
            "counter": (["width"], ["leak", "access"]),
            "comparator": (["width"], ["leak", "access"]),
            "crossbar": (["n_inputs", "n_outputs", "width"], ["leak", "access"]),
            "wire": (["length", "width"], ["transfer", "transfer_random"]),
            "FIFO": (["width", "depth"], ["leak", "access"]),
            "bitwise": (["width"], ["leak", "access"]),
            "intadder": (["width"], ["leak", "access"]),
            "intmultiplier": (["width"], ["leak", "access"]),
            "intmac": (["width"], ["leak", "access"]),
            "fpadder": (["exponent", "mantissa"], ["leak", "access"]),
            "fpmultiplier": (["exponent", "mantissa"], ["leak", "access"]),
            "fpmac": (["exponent", "mantissa"], ["leak", "access"]),
            "reg": (["width"], ["leak", "access"]),
        }
        supported = []
        for c, (attrs, actions) in components.items():
            attrs = ["technology", "global_cycle_seconds"] + attrs
            supported.append(
                SupportedComponent(
                    c,
                    PrintableCall("", attrs),
                    [PrintableCall(a) for a in actions],
                )
            )

        return supported


# --------------------------------------------------------------------------
# ART-related functions
# ---------------------------------------------------------------------------
class AladdinAreaQueires:
    def __init__(self, supported_pc):
        # example primitive classes supported by this estimator
        self.supported_pc = supported_pc

    def estimate_area(self, interface):
        class_name = interface["class_name"]
        query_function_name = class_name + "_estimate_area"
        area = getattr(self, query_function_name)(interface)
        return area

    @staticmethod
    def query_csv_area_using_latency(interface, csv_file_path):
        # default latency for Aladdin estimation is
        if "latency" in interface["attributes"]:
            latency = interface["attributes"]["latency"]
        else:
            latency = 5
        # round to an exist
        # ing latency (can perform linear interpolation as well)
        if isinstance(latency, str) and "ns" in latency:
            latency = math.ceil(float(latency.split("ns")[0]))
        else:
            latency = math.ceil(latency)
        if latency > 10:
            latency = 10
        elif latency > 6:
            latency = 6
        # there are only two types of energy in Aladdin tables
        with open(csv_file_path) as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                if row["latency(ns)"] == str(latency):
                    area = float(row["area(um^2)"])
                    break
        return area

    def SRAM_estimate_area(self, interface):
        return self.regfile_estimate_area(interface)

    def regfile_estimate_area(self, interface):
        # register file access is naively modeled as vector access of registers
        # register energy consumption is generated according to latency

        width = interface["attributes"]["width"]
        depth = interface["attributes"]["depth"]
        this_dir, this_filename = os.path.split(__file__)
        csv_file_path = os.path.join(this_dir, "data/reg.csv")
        if depth == 0:
            return 0
        reg_interface = deepcopy(interface)
        reg_area = AladdinAreaQueires.query_csv_area_using_latency(
            reg_interface, csv_file_path
        )
        comparator_interface = {
            "attributes": {"width": math.ceil(math.log2(float(depth)))}
        }
        comparator_area = self.comparator_estimate_area(comparator_interface)
        # register file access is naively modeled as vector access of registers
        reg_file_area = reg_area * width + comparator_area * depth
        return reg_file_area

    def reg_estimate_area(self, interface):
        this_dir, this_filename = os.path.split(__file__)
        reg_interface = deepcopy(interface)
        csv_file_path = os.path.join(this_dir, "data/reg.csv")
        reg_area = AladdinAreaQueires.query_csv_area_using_latency(
            reg_interface, csv_file_path
        )
        return reg_area

    def FIFO_estimate_area(self, interface):
        datawidth = interface["attributes"]["width"]
        depth = interface["attributes"]["depth"]
        if depth == 0:
            return 0
        this_dir, this_filename = os.path.split(__file__)
        csv_file_path = os.path.join(this_dir, "data/reg.csv")
        reg_area = AladdinAreaQueires.query_csv_area_using_latency(
            interface, csv_file_path
        )
        comparator_interface = {"attributes": {"width": math.log2(float(depth))}}
        comparator_area = self.comparator_estimate_area(comparator_interface)
        area = reg_area * datawidth + comparator_area
        return area

    def crossbar_estimate_area(self, interface):
        n_inputs = interface["attributes"]["n_inputs"]
        n_outputs = interface["attributes"]["n_outputs"]
        datawidth = interface["attributes"]["width"]
        this_dir, this_filename = os.path.split(__file__)
        csv_file_path = os.path.join(this_dir, "data/crossbar.csv")
        csv_area = AladdinAreaQueires.query_csv_area_using_latency(
            interface, csv_file_path
        )
        crossbar_area = csv_area * n_inputs * (n_outputs / 4) * (datawidth / 32)
        return crossbar_area

    def counter_estimate_area(self, interface):
        width = interface["attributes"]["width"]
        this_dir, this_filename = os.path.split(__file__)
        csv_file_path = os.path.join(this_dir, "data/counter.csv")
        csv_energy = AladdinAreaQueires.query_csv_area_using_latency(
            interface, csv_file_path
        )
        energy = csv_energy * (width / 32)
        return energy

    def comparator_estimate_area(self, interface):
        datawidth = interface["attributes"]["width"]
        this_dir, this_filename = os.path.split(__file__)
        csv_file_path = os.path.join(this_dir, "data/comparator.csv")
        csv_area = AladdinAreaQueires.query_csv_area_using_latency(
            interface, csv_file_path
        )
        area = csv_area * (datawidth / 32)
        return area

    def wire_estimate_area(self, interface):
        # ignore the area of the wires
        return 0

    def intmac_estimate_area(self, interface):
        # mac is naively modeled as adder and multiplier
        adder_area = self.intadder_estimate_area(interface)
        multiplier_area = self.intmultiplier_estimate_area(interface)
        area = adder_area + multiplier_area
        return area

    def fpmac_estimate_area(self, interface):
        # fpmac is naively modeled as fpadder and fpmultiplier
        fpadder_area = self.fpadder_estimate_area(interface)
        fpmultiplier_area = self.fpmultiplier_estimate_area(interface)
        area = fpadder_area + fpmultiplier_area
        return area

    def intadder_estimate_area(self, interface):
        this_dir, this_filename = os.path.split(__file__)
        nbit = interface["attributes"]["width"]
        csv_nbit = 32
        csv_file_path = os.path.join(this_dir, "data/adder.csv")
        area = AladdinAreaQueires.query_csv_area_using_latency(interface, csv_file_path)
        if not nbit == csv_nbit:
            area = oneD_linear_interpolation(
                nbit, [{"x": 0, "y": 0}, {"x": csv_nbit, "y": area}]
            )
        return area

    def fpadder_estimate_area(self, interface):
        this_dir, this_filename = os.path.split(__file__)
        nbit_exponent = interface["attributes"]["exponent"]
        nbit_mantissa = interface["attributes"]["mantissa"]
        nbit = nbit_mantissa + nbit_exponent
        if nbit_exponent + nbit_mantissa <= 32:
            csv_nbit = 32
            csv_file_path = os.path.join(this_dir, "data/fp_sp_adder.csv")
        else:
            csv_nbit = 64
            csv_file_path = os.path.join(this_dir, "data/fp_dp_adder.csv")
        area = AladdinAreaQueires.query_csv_area_using_latency(interface, csv_file_path)
        if not nbit == csv_nbit:
            area = oneD_linear_interpolation(
                nbit, [{"x": 0, "y": 0}, {"x": csv_nbit, "y": area}]
            )
        return area

    def intmultiplier_estimate_area(self, interface):
        this_dir, this_filename = os.path.split(__file__)
        nbit = interface["attributes"]["width"]
        csv_nbit = 32
        csv_file_path = os.path.join(this_dir, "data/multiplier.csv")
        area = AladdinAreaQueires.query_csv_area_using_latency(interface, csv_file_path)
        if not nbit == csv_nbit:
            area = oneD_quadratic_interpolation(
                nbit, [{"x": 0, "y": 0}, {"x": csv_nbit, "y": area}]
            )
        return area

    def fpmultiplier_estimate_area(self, interface):
        this_dir, this_filename = os.path.split(__file__)
        nbit_exponent = interface["attributes"]["exponent"]
        nbit_mantissa = interface["attributes"]["mantissa"]
        nbit = nbit_mantissa + nbit_exponent
        if nbit_exponent + nbit_mantissa <= 32:
            csv_nbit = 32
            csv_file_path = os.path.join(this_dir, "data/fp_sp_multiplier.csv")
        else:
            csv_nbit = 64
            csv_file_path = os.path.join(this_dir, "data/fp_dp_multiplier.csv")
        area = AladdinAreaQueires.query_csv_area_using_latency(interface, csv_file_path)
        if not nbit == csv_nbit:
            area = oneD_quadratic_interpolation(
                nbit, [{"x": 0, "y": 0}, {"x": csv_nbit, "y": area}]
            )
        return area

    def bitwise_estimate_area(self, interface):
        this_dir, this_filename = os.path.split(__file__)
        csv_file_path = os.path.join(this_dir, "data/bitwise.csv")
        csv_area = AladdinAreaQueires.query_csv_area_using_latency(
            interface, csv_file_path
        )
        return csv_area
