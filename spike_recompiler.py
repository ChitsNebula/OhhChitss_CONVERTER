import zipfile
import json
import io
import ast
import re
import os
import random
import string
import datetime


def gen_id(length=12):
    chars = string.ascii_letters + string.digits
    return "".join(random.choice(chars) for _ in range(length))


def clean_identifier(name):
    if not name:
        return "var"
    cleaned = re.sub(r'[^a-zA-Z0-9_\u0e00-\u0e7f]', '_', name)
    if cleaned[0].isdigit():
        cleaned = "_" + cleaned
    if cleaned in ("def", "class", "if", "else", "elif", "while", "for", "in", "import", "from", "return", "pass", "and", "or", "not", "is"):
        cleaned = cleaned + "_"
    return cleaned



class Recompiler:
    def __init__(self):
        self.blocks = {}
        self.variables = {}   # name -> id
        self.procedures = {}  # name -> {arg_ids, arg_names, proccode}
        self.warnings = []
        self.list_names = set()
        self.curr_func = None



    # ─── helpers ────────────────────────────────────────────────────────────

    def add_var(self, name):
        if name not in self.variables:
            self.variables[name] = gen_id()
        return self.variables[name]

    def add_block(self, bid, opcode, next_id=None, parent_id=None,
                  inputs=None, fields=None, shadow=False,
                  top_level=False, x=0, y=0):
        b = {
            "opcode": opcode,
            "next": next_id,
            "parent": parent_id,
            "inputs": inputs or {},
            "fields": fields or {},
            "shadow": shadow,
            "topLevel": top_level,
        }
        if top_level:
            b["x"] = x
            b["y"] = y
        self.blocks[bid] = b
        return bid

    # ─── input makers ───────────────────────────────────────────────────────

    def lit_input(self, value):
        if isinstance(value, (int, float)):
            return [1, [4, str(value)]]
        return [1, [10, str(value)]]

    def var_input(self, name):
        vid = self.add_var(name)
        if name in self.list_names:
            return [3, [13, name, vid], [10, ""]]
        return [3, [12, name, vid], [10, ""]]

    def port_input(self, node, parent_id, selector_type):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            port_val = node.value
            shadow_id = gen_id(length=12)
            field_name = f"field_{selector_type}"
            if "menu_acceleration" in selector_type:
                field_name = "acceleration"
            self.add_block(shadow_id, selector_type, parent_id=parent_id, fields={
                field_name: [port_val, None]
            }, shadow=True)
            return [1, shadow_id]
        return self.expr_to_input(node, parent_id)

    def direction_input(self, node, parent_id, shadow_opcode):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            dir_val = node.value
            shadow_id = gen_id(length=12)
            self.add_block(shadow_id, shadow_opcode, parent_id=parent_id, fields={
                f"field_{shadow_opcode}": [dir_val, None]
            }, shadow=True)
            return [1, shadow_id]
        return self.expr_to_input(node, parent_id)




    def block_input(self, bid):
        return [2, bid]

    # ─── expression → input ─────────────────────────────────────────────────

    def expr_to_input(self, node, parent_id):
        if node is None:
            return self.lit_input(0)

        if isinstance(node, ast.Constant):
            return self.lit_input(node.value)

        if isinstance(node, ast.Name):
            if node.id in ("True", "False"):
                return self.lit_input(1 if node.id == "True" else 0)
            
            # Check if it is a parameter of the current function
            if self.curr_func and node.id in self.procedures[self.curr_func]["arg_names"]:
                idx = self.procedures[self.curr_func]["arg_names"].index(node.id)
                disp_name = self.procedures[self.curr_func]["display_arg_names"][idx]
                bid = gen_id()
                self.add_block(bid, "argument_reporter_string_number", parent_id=parent_id,
                               fields={"VALUE": [disp_name, None]}, shadow=False)
                return [2, bid]
                
            return self.var_input(node.id)

        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            if isinstance(node.operand, ast.Constant):
                return self.lit_input(-node.operand.value)

        # compound expression → compile to a block
        bid = self.compile_expr(node, parent_id)
        if bid:
            return self.block_input(bid)

        self.warnings.append(f"Cannot convert expression: {ast.dump(node)}")
        return self.lit_input(0)

    # ─── expression → block ─────────────────────────────────────────────────

    def compile_expr(self, node, parent_id):
        bid = gen_id()

        # Binary operators
        if isinstance(node, ast.BinOp):
            op_map = {
                ast.Add:  ("operator_add",      "NUM1", "NUM2"),
                ast.Sub:  ("operator_subtract", "NUM1", "NUM2"),
                ast.Mult: ("operator_multiply", "NUM1", "NUM2"),
                ast.Div:  ("operator_divide",   "NUM1", "NUM2"),
            }
            for op_type, (opcode, in1, in2) in op_map.items():
                if isinstance(node.op, op_type):
                    self.add_block(bid, opcode, parent_id=parent_id, inputs={
                        in1: self.expr_to_input(node.left,  bid),
                        in2: self.expr_to_input(node.right, bid),
                    })
                    return bid
            self.warnings.append(f"Unsupported operator: {type(node.op).__name__}")
            return None

        # Comparisons
        if isinstance(node, ast.Compare):
            if len(node.ops) == 2 and isinstance(node.ops[0], (ast.LtE, ast.Lt)) and isinstance(node.ops[1], (ast.LtE, ast.Lt)):
                self.add_block(bid, "flipperoperator_isInBetween", parent_id=parent_id, inputs={
                    "LOW": self.expr_to_input(node.left, bid),
                    "VALUE": self.expr_to_input(node.comparators[0], bid),
                    "HIGH": self.expr_to_input(node.comparators[1], bid),
                })
                return bid

            if len(node.ops) == 1:
                op = node.ops[0]
                cmp = node.comparators[0]
                if isinstance(op, ast.In):
                    self.add_block(bid, "operator_contains", parent_id=parent_id, inputs={
                        "STRING1": self.expr_to_input(cmp, bid),
                        "STRING2": self.expr_to_input(node.left, bid),
                    })
                    return bid

                op_map = {
                    ast.Eq:  "operator_equals",
                    ast.Gt:  "operator_gt",
                    ast.Lt:  "operator_lt",
                    ast.GtE: "operator_gt",
                    ast.LtE: "operator_lt",
                }

                # Check for flippersensors_isReflectivity shortcut
                # color_sensor.reflectivity(port) <cmp> value
                if isinstance(node.left, ast.Call) and type(op) in op_map:
                    obj, method, c_args, _ = self._call_parts(node.left)
                    if obj == "color_sensor" and method == "reflectivity":
                        port = c_args[0] if c_args else ast.Constant(value="A")
                        comp_str = "=" if type(op) == ast.Eq else (">" if type(op) in (ast.Gt, ast.GtE) else "<")
                        self.add_block(bid, "flippersensors_isReflectivity", parent_id=parent_id, inputs={
                            "PORT": self.port_input(port, bid, "flippersensors_color-sensor-selector"),
                            "VALUE": self.expr_to_input(cmp, bid),
                        }, fields={
                            "COMPARATOR": [comp_str, None]
                        })
                        return bid

                opcode = op_map.get(type(op))
                if opcode:
                    self.add_block(bid, opcode, parent_id=parent_id, inputs={
                        "OPERAND1": self.expr_to_input(node.left, bid),
                        "OPERAND2": self.expr_to_input(cmp, bid),
                    })
                    return bid
            self.warnings.append("Unsupported comparison type")
            return None



        # Boolean ops
        if isinstance(node, ast.BoolOp):
            opcode = "operator_and" if isinstance(node.op, ast.And) else "operator_or"
            left = node.values[0]
            right = node.values[1] if len(node.values) > 1 else node.values[0]
            self.add_block(bid, opcode, parent_id=parent_id, inputs={
                "OPERAND1": self.expr_to_input(left,  bid),
                "OPERAND2": self.expr_to_input(right, bid),
            })
            return bid

        # not X
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            self.add_block(bid, "operator_not", parent_id=parent_id, inputs={
                "OPERAND": self.expr_to_input(node.operand, bid),
            })
            return bid

        # Function calls that return values
        if isinstance(node, ast.Call):
            return self.compile_expr_call(node, parent_id)

        # Subscript like mylist[i]
        if isinstance(node, ast.Subscript):
            if isinstance(node.value, ast.Name):
                list_name = node.value.id
                vid = self.add_var(list_name)
                # index: 1-based in Scratch
                index = node.slice
                self.add_block(bid, "data_itemoflist", parent_id=parent_id, inputs={
                    "INDEX": self.expr_to_input(index, bid),
                }, fields={"LIST": [list_name, vid]})
                return bid

        # len(list)
        if isinstance(node, ast.Call):
            return self.compile_expr_call(node, parent_id)

        self.warnings.append(f"Cannot compile expression: {type(node).__name__}")
        return None

    def compile_expr_call(self, node, parent_id):
        obj, method, args, kwargs = self._call_parts(node)
        bid = gen_id()

        if obj is None and method == "abs":

            num = args[0] if args else ast.Constant(value=0)
            self.add_block(bid, "operator_mathop", parent_id=parent_id,
                           inputs={"NUM": self.expr_to_input(num, bid)},
                           fields={"OPERATOR": ["abs", None]})
            return bid

        if obj == "time" and method == "time":
            self.add_block(bid, "flippersensors_timer", parent_id=parent_id)
            return bid

        if obj == "color_sensor" and method == "color":
            port = args[0] if args else None
            inputs = {}
            if port:
                inputs["PORT"] = self.port_input(port, bid, "flippersensors_color-sensor-selector")
            self.add_block(bid, "flippersensors_color", parent_id=parent_id, inputs=inputs)
            return bid

        if obj == "color_sensor" and method == "reflectivity":
            port = args[0] if args else ast.Constant(value="A")
            self.add_block(bid, "flippersensors_reflectivity", parent_id=parent_id,
                           inputs={"PORT": self.port_input(port, bid, "flippersensors_color-sensor-selector")})
            return bid

        if obj == "color_sensor" and method == "is_color":
            port  = args[0] if args else ast.Constant(value="A")
            color = args[1] if len(args) > 1 else ast.Constant(value="black")
            self.add_block(bid, "flippersensors_isColor", parent_id=parent_id,
                           inputs={"PORT": self.port_input(port, bid, "flippersensors_color-sensor-selector"),
                                   "COLOR": self.port_input(color, bid, "flippersensors_color-selector")})
            return bid

        if obj == "distance_sensor" and method == "get_distance_percentage":
            port = args[0] if args else ast.Constant(value="A")
            self.add_block(bid, "flippersensors_distance", parent_id=parent_id,
                           inputs={"PORT": self.port_input(port, bid, "flippersensors_distance-sensor-selector")})
            return bid

        if obj == "force_sensor" and method == "get_force_newton":
            port = args[0] if args else ast.Constant(value="A")
            self.add_block(bid, "flippersensors_force", parent_id=parent_id,
                           inputs={"PORT": self.port_input(port, bid, "flippersensors_force-sensor-selector")})
            return bid

        if obj == "force_sensor" and method == "is_pressed":
            port = args[0] if args else ast.Constant(value="F")
            opt_val = args[1].value if len(args) > 1 and isinstance(args[1], ast.Constant) else "pressed"
            self.add_block(bid, "flippersensors_isPressed", parent_id=parent_id,
                           inputs={"PORT": self.port_input(port, bid, "flippersensors_force-sensor-selector")},
                           fields={"OPTION": [opt_val, None]})
            return bid

        if obj == "motor" and method == "position":
            port = args[0] if args else ast.Constant(value="A")
            sel_type = "flippermotor_multiple-port-selector" if isinstance(port, ast.Constant) and isinstance(port.value, str) and len(port.value) > 1 else "flippermotor_single-motor-selector"
            self.add_block(bid, "flippermoremotor_position", parent_id=parent_id,
                           inputs={"PORT": self.port_input(port, bid, sel_type)})
            return bid

        if obj == "motor" and method == "degrees_counted":
            port = args[0] if args else ast.Constant(value="A")
            sel_type = "flippermotor_multiple-port-selector" if isinstance(port, ast.Constant) and isinstance(port.value, str) and len(port.value) > 1 else "flippermotor_single-motor-selector"
            self.add_block(bid, "flippermoremotor_degrees", parent_id=parent_id,
                           inputs={"PORT": self.port_input(port, bid, sel_type)})
            return bid


        if obj == "math":
            num = args[0] if args else ast.Constant(value=0)
            self.add_block(bid, "operator_mathop", parent_id=parent_id,
                           inputs={"NUM": self.expr_to_input(num, bid)},
                           fields={"OPERATOR": [method, None]})
            return bid

        if obj is None and method == "len" and args:
            target = args[0]
            if isinstance(target, ast.Name):
                vid = self.add_var(target.id)
                self.add_block(bid, "data_lengthoflist", parent_id=parent_id,
                               fields={"LIST": [target.id, vid]})
                return bid

        if isinstance(node.func, ast.Attribute):
            # hub.motion.orientation
            func_val = node.func.value
            if (isinstance(func_val, ast.Attribute) and
                    isinstance(func_val.value, ast.Name) and
                    func_val.value.id == "hub" and func_val.attr == "motion" and
                    node.func.attr == "orientation"):
                axis = args[0].value if args and isinstance(args[0], ast.Constant) else "yaw"
                self.add_block(bid, "flippersensors_orientationAxis", parent_id=parent_id,
                               fields={"AXIS": [axis, None]})
                return bid

        self.warnings.append(f"Cannot convert expression call: {obj}.{method}")
        return None


    # ─── statement → [block_ids] ────────────────────────────────────────────

    def compile_stmt(self, node, parent_id):
        # Variable assignment
        if isinstance(node, ast.Assign):
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                var_name = node.targets[0].id
                # Skip hub / movement / motor alias assignments
                if isinstance(node.value, ast.Call):
                    obj, method, _, _ = self._call_parts(node.value)
                    if obj in (None,) and method in ("PrimeHub", "MotorGroup", "Motor",
                                                     "ColorSensor", "DistanceSensor",
                                                     "ForceSensor"):
                        return []
                    if isinstance(node.value.func, ast.Name):
                        if node.value.func.id in ("PrimeHub", "MotorGroup", "Motor",
                                                   "ColorSensor", "DistanceSensor",
                                                   "ForceSensor"):
                            return []
                vid = self.add_var(var_name)
                bid = gen_id()
                self.add_block(bid, "data_setvariableto", parent_id=parent_id,
                               inputs={"VALUE": self.expr_to_input(node.value, bid)},
                               fields={"VARIABLE": [var_name, vid]})
                return [bid]

            # List subscript assignment  mylist[i] = v
            if (len(node.targets) == 1 and
                    isinstance(node.targets[0], ast.Subscript) and
                    isinstance(node.targets[0].value, ast.Name)):
                list_name = node.targets[0].value.id
                vid = self.add_var(list_name)
                index = node.targets[0].slice
                bid = gen_id()
                self.add_block(bid, "data_replaceitemoflist", parent_id=parent_id,
                               inputs={"INDEX": self.expr_to_input(index, bid),
                                       "ITEM":  self.expr_to_input(node.value, bid)},
                               fields={"LIST": [list_name, vid]})
                return [bid]

            self.warnings.append("Complex assignment skipped")
            return []

        # Augmented assignment  var += value
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            var_name = node.target.id
            vid = self.add_var(var_name)
            bid = gen_id()
            if isinstance(node.op, ast.Add):
                self.add_block(bid, "data_changevariableby", parent_id=parent_id,
                               inputs={"VALUE": self.expr_to_input(node.value, bid)},
                               fields={"VARIABLE": [var_name, vid]})
                return [bid]

            op_map = {ast.Add: "operator_add", ast.Sub: "operator_subtract",
                      ast.Mult: "operator_multiply", ast.Div: "operator_divide"}
            opcode = op_map.get(type(node.op), "operator_add")
            binop_bid = gen_id()
            self.add_block(binop_bid, opcode, parent_id=bid,
                           inputs={"NUM1": self.var_input(var_name),
                                   "NUM2": self.expr_to_input(node.value, binop_bid)})
            self.add_block(bid, "data_setvariableto", parent_id=parent_id,
                           inputs={"VALUE": [3, binop_bid, [4, "0"]]},
                           fields={"VARIABLE": [var_name, vid]})
            return [bid]


        # Expression statement (function call)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            return self._compile_call_stmt(node.value, parent_id)

        # If / If-Else
        if isinstance(node, ast.If):
            cond_bid = self.compile_expr(node.test, None)
            cond_input = (self.block_input(cond_bid) if cond_bid
                          else self.lit_input(True))
            if cond_bid:
                self.blocks[cond_bid]["parent"] = None  # will be set below

            if node.orelse:
                bid = gen_id()
                self.add_block(bid, "control_if_else", parent_id=parent_id,
                               inputs={"CONDITION": cond_input})
                if cond_bid:
                    self.blocks[cond_bid]["parent"] = bid
                body_ids = self.compile_body(node.body, bid)
                else_ids = self.compile_body(node.orelse, bid)
                if body_ids:
                    self.blocks[bid]["inputs"]["SUBSTACK"] = [2, body_ids[0]]
                if else_ids:
                    self.blocks[bid]["inputs"]["SUBSTACK2"] = [2, else_ids[0]]
                return [bid]
            else:
                bid = gen_id()
                self.add_block(bid, "control_if", parent_id=parent_id,
                               inputs={"CONDITION": cond_input})
                if cond_bid:
                    self.blocks[cond_bid]["parent"] = bid
                body_ids = self.compile_body(node.body, bid)
                if body_ids:
                    self.blocks[bid]["inputs"]["SUBSTACK"] = [2, body_ids[0]]
                return [bid]

        # While loop
        if isinstance(node, ast.While):
            # check if it is a "wait until" pattern:
            # while not X: time.sleep(0.01)
            is_wait_until = False
            test = node.test
            if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
                if len(node.body) == 1:
                    stmt = node.body[0]
                    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                        obj, method, _, _ = self._call_parts(stmt.value)
                        if obj == "time" and method == "sleep":
                            is_wait_until = True

            if is_wait_until:
                bid = gen_id()
                cond_bid = self.compile_expr(test.operand, bid)
                cond_input = self.block_input(cond_bid) if cond_bid else self.lit_input(True)
                self.add_block(bid, "control_wait_until", parent_id=parent_id,
                               inputs={"CONDITION": cond_input})
                if cond_bid:
                    self.blocks[cond_bid]["parent"] = bid
                return [bid]

            # while True → forever
            if isinstance(node.test, ast.Constant) and node.test.value is True:
                bid = gen_id()
                self.add_block(bid, "control_forever", parent_id=parent_id)
                body_ids = self.compile_body(node.body, bid)
                if body_ids:
                    self.blocks[bid]["inputs"]["SUBSTACK"] = [2, body_ids[0]]
                return [bid]

            # while not X → repeat until X
            test = node.test
            if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
                cond_bid = self.compile_expr(test.operand, None)
            else:
                cond_bid = self.compile_expr(test, None)

            cond_input = (self.block_input(cond_bid) if cond_bid
                          else self.lit_input(True))
            bid = gen_id()
            self.add_block(bid, "control_repeat_until", parent_id=parent_id,
                           inputs={"CONDITION": cond_input})
            if cond_bid:
                self.blocks[cond_bid]["parent"] = bid
            body_ids = self.compile_body(node.body, bid)
            if body_ids:
                self.blocks[bid]["inputs"]["SUBSTACK"] = [2, body_ids[0]]
            return [bid]


        # For loop (simple range)
        if isinstance(node, ast.For):
            # for _ in range(n)  → repeat n times
            if (isinstance(node.iter, ast.Call) and
                    isinstance(node.iter.func, ast.Name) and
                    node.iter.func.id == "range"):
                args = node.iter.args
                count = args[0] if len(args) == 1 else None
                if count:
                    bid = gen_id()
                    self.add_block(bid, "control_repeat", parent_id=parent_id,
                                   inputs={"TIMES": self.expr_to_input(count, bid)})
                    body_ids = self.compile_body(node.body, bid)
                    if body_ids:
                        self.blocks[bid]["inputs"]["SUBSTACK"] = [2, body_ids[0]]
                    return [bid]

            self.warnings.append(f"For loop (not simple range) skipped — added as comment")
            return []

        # Skip these silently
        if isinstance(node, (ast.Global, ast.Return, ast.Pass,
                              ast.Import, ast.ImportFrom)):
            return []
        if isinstance(node, ast.Expr):
            return []

        self.warnings.append(f"Unsupported statement '{type(node).__name__}' — skipped")
        return []

    def _compile_call_stmt(self, node, parent_id):
        obj, method, args, kwargs = self._call_parts(node)
        bid = gen_id()

        def get_arg(i, default=0):
            return args[i] if len(args) > i else ast.Constant(value=default)

        def get_kwarg(key, default):
            return kwargs.get(key, ast.Constant(value=default))

        def get_kwarg_str(key, default):
            n = get_kwarg(key, default)
            return n.value if isinstance(n, ast.Constant) else default

        # ── movement ──────────────────────────────────────────────────────
        if obj == "movement" and method == "move":
            unit = get_kwarg_str("unit", "cm")
            self.add_block(bid, "flippermove_move", parent_id=parent_id,
                           inputs={"VALUE":     self.expr_to_input(get_arg(0), bid),
                                   "DIRECTION": self.direction_input(get_kwarg("direction", "forward"), bid, "flippermove_custom-icon-direction")},
                           fields={"UNIT": [unit, None]})
            return [bid]

        if obj == "movement" and method == "speed":
            self.add_block(bid, "flippermove_movementSpeed", parent_id=parent_id,
                           inputs={"SPEED": self.expr_to_input(get_arg(0, 50), bid)})
            return [bid]

        if obj == "movement" and method == "stop":
            self.add_block(bid, "flippermove_stopMove", parent_id=parent_id)
            return [bid]

        if obj == "movement" and method == "steer":
            unit = get_kwarg_str("unit", "cm")
            self.add_block(bid, "flippermove_steer", parent_id=parent_id,
                           inputs={"STEERING": self.expr_to_input(get_arg(0, 0), bid),
                                   "VALUE":    self.expr_to_input(get_arg(1, 0), bid)},
                           fields={"UNIT": [unit, None]})
            return [bid]

        if obj == "movement" and method == "pair":
            self.add_block(bid, "flippermove_setMovementPair", parent_id=parent_id,
                           inputs={"PAIR": self.port_input(get_arg(0, "CD"), bid, "flippermove_movement-port-selector")})
            return [bid]

        if obj == "movement" and method == "start_dual_speed":
            self.add_block(bid, "flippermoremove_startDualSpeed", parent_id=parent_id,
                           inputs={"LEFT": self.expr_to_input(get_arg(0, 50), bid),
                                   "RIGHT": self.expr_to_input(get_arg(1, 50), bid)})
            return [bid]

        if obj == "movement" and method == "set_acceleration":
            self.add_block(bid, "flippermoremove_movementSetAcceleration", parent_id=parent_id,
                           inputs={"ACCELERATION": self.port_input(get_arg(0, "3000 3000"), bid, "flippermoremove_menu_acceleration")})
            return [bid]

        # ── motor ─────────────────────────────────────────────────────────
        if obj == "motor" and method == "turn":
            unit = get_kwarg_str("unit", "degrees")
            port = get_arg(0, "A")
            sel_type = "flippermotor_multiple-port-selector" if isinstance(port, ast.Constant) and isinstance(port.value, str) and len(port.value) > 1 else "flippermotor_single-motor-selector"
            self.add_block(bid, "flippermotor_motorTurnForDirection", parent_id=parent_id,
                           inputs={"PORT":      self.port_input(port, bid, sel_type),
                                   "DIRECTION": self.direction_input(get_arg(1, "clockwise"), bid, "flippermotor_custom-icon-direction"),
                                   "VALUE":     self.expr_to_input(get_arg(2, 0), bid)},
                           fields={"UNIT": [unit, None]})
            return [bid]

        if obj == "motor" and method == "start_power":
            port = get_arg(0, "A")
            sel_type = "flippermotor_multiple-port-selector" if isinstance(port, ast.Constant) and isinstance(port.value, str) and len(port.value) > 1 else "flippermotor_single-motor-selector"
            self.add_block(bid, "flippermoremotor_motorStartPower", parent_id=parent_id,
                           inputs={"PORT":  self.port_input(port, bid, sel_type),
                                   "POWER": self.expr_to_input(get_arg(1, 50), bid)})
            return [bid]

        if obj == "motor" and method == "set_degrees_counted":
            port = get_arg(0, "A")
            sel_type = "flippermotor_multiple-port-selector" if isinstance(port, ast.Constant) and isinstance(port.value, str) and len(port.value) > 1 else "flippermotor_single-motor-selector"
            self.add_block(bid, "flippermoremotor_motorSetDegreeCounted", parent_id=parent_id,
                           inputs={"PORT":  self.port_input(port, bid, sel_type),
                                   "VALUE": self.expr_to_input(get_arg(1, 0), bid)})
            return [bid]

        if obj == "motor" and method == "go_to_relative_position":
            dir_val = get_kwarg_str("direction", "shortest path")
            port = get_arg(0, "A")
            sel_type = "flippermotor_multiple-port-selector" if isinstance(port, ast.Constant) and isinstance(port.value, str) and len(port.value) > 1 else "flippermotor_single-motor-selector"
            inputs = {
                "PORT":     self.port_input(port, bid, sel_type),
                "POSITION": self.expr_to_input(get_arg(1, 0), bid)
            }
            if "speed" in kwargs:
                inputs["SPEED"] = self.expr_to_input(kwargs["speed"], bid)
            elif len(args) > 2:
                inputs["SPEED"] = self.expr_to_input(args[2], bid)
            self.add_block(bid, "flippermoremotor_motorGoToRelativePosition", parent_id=parent_id,
                           inputs=inputs,
                           fields={"DIRECTION": [dir_val, None]})
            return [bid]

        if obj == "motor" and method == "set_stop_method":
            stop_type = get_kwarg_str("type", "hold") if "type" in kwargs else (
                args[1].value if len(args) > 1 and isinstance(args[1], ast.Constant) else "hold")
            
            stop_map = {
                "coast": "0", "float": "0", "0": "0",
                "brake": "1", "1": "1",
                "hold": "2", "hold position": "2", "2": "2"
            }
            stop_code = stop_map.get(str(stop_type).lower(), "2")
            
            port = get_arg(0, "A")
            sel_type = "flippermotor_multiple-port-selector" if isinstance(port, ast.Constant) and isinstance(port.value, str) and len(port.value) > 1 else "flippermotor_single-motor-selector"
            self.add_block(bid, "flippermoremotor_motorSetStopMethod", parent_id=parent_id,
                           inputs={"PORT": self.port_input(port, bid, sel_type)},
                           fields={"STOP": [stop_code, None]})
            return [bid]

        if obj == "motor" and method == "set_acceleration":
            port = get_arg(0, "A")
            sel_type = "flippermotor_multiple-port-selector" if isinstance(port, ast.Constant) and isinstance(port.value, str) and len(port.value) > 1 else "flippermotor_single-motor-selector"
            self.add_block(bid, "flippermoremotor_motorSetAcceleration", parent_id=parent_id,
                           inputs={"PORT":         self.port_input(port, bid, sel_type),
                                   "ACCELERATION": self.port_input(get_arg(1, "1000 1000"), bid, "flippermoremotor_menu_acceleration")})
            return [bid]

        if obj == "motor" and method == "set_speed":
            port = get_arg(0, "A")
            sel_type = "flippermotor_multiple-port-selector" if isinstance(port, ast.Constant) and isinstance(port.value, str) and len(port.value) > 1 else "flippermotor_single-motor-selector"
            self.add_block(bid, "flippermotor_motorSetSpeed", parent_id=parent_id,
                           inputs={"PORT":  self.port_input(port, bid, sel_type),
                                   "SPEED": self.expr_to_input(get_arg(1, 75), bid)})
            return [bid]

        # ── time / sys / sensors ──────────────────────────────────────────
        if obj == "time" and method == "sleep":
            self.add_block(bid, "control_wait", parent_id=parent_id,
                           inputs={"DURATION": self.expr_to_input(get_arg(0, 1), bid)})
            return [bid]

        if obj == "sys" and method == "exit":
            self.add_block(bid, "flippercontrol_stop", parent_id=parent_id)
            return [bid]

        if obj == "sensors" and method == "reset_timer":
            self.add_block(bid, "flippersensors_resetTimer", parent_id=parent_id)
            return [bid]

        # ── sound ─────────────────────────────────────────────────────────
        if obj == "sound" and method == "beep":
            note_node = get_arg(0, 60)
            if isinstance(note_node, ast.Constant):
                note_val = str(note_node.value)
                shadow_id = gen_id(length=12)
                self.add_block(shadow_id, "flippersound_custom-piano", parent_id=bid, fields={
                    "field_flippersound_custom-piano": [note_val, None]
                }, shadow=True)
                note_in = [1, shadow_id]
            else:
                note_in = self.expr_to_input(note_node, bid)

            self.add_block(bid, "flippersound_beepForTime", parent_id=parent_id,
                           inputs={"NOTE":     note_in,
                                   "DURATION": self.expr_to_input(get_arg(1, 0.2), bid)})
            return [bid]

        if obj == "sound" and method == "volume":
            self.add_block(bid, "sound_setvolumeto", parent_id=parent_id,
                           inputs={"VOLUME": self.expr_to_input(get_arg(0, 100), bid)})
            return [bid]

            return [bid]

        # ── sensors ───────────────────────────────────────────────────────
        if obj == "sensors" and method == "reset_yaw":
            self.add_block(bid, "flippersensors_resetYaw", parent_id=parent_id)
            return [bid]

        # ── list operations ───────────────────────────────────────────────
        if obj is None and isinstance(node.func, ast.Attribute):
            # mylist.append(item)
            if method == "append" and isinstance(node.func.value, ast.Name):
                list_name = node.func.value.id
                vid = self.add_var(list_name)
                self.add_block(bid, "data_addtolist", parent_id=parent_id,
                               inputs={"ITEM": self.expr_to_input(get_arg(0, ""), bid)},
                               fields={"LIST": [list_name, vid]})
                return [bid]

            if method == "insert" and isinstance(node.func.value, ast.Name):
                list_name = node.func.value.id
                vid = self.add_var(list_name)
                self.add_block(bid, "data_insertatlist", parent_id=parent_id,
                               inputs={"ITEM":  self.expr_to_input(get_arg(1, ""), bid),
                                       "INDEX": self.expr_to_input(get_arg(0, 1), bid)},
                               fields={"LIST": [list_name, vid]})
                return [bid]

            if method in ("pop", "remove") and isinstance(node.func.value, ast.Name):
                list_name = node.func.value.id
                vid = self.add_var(list_name)
                index = get_arg(0, "last")
                self.add_block(bid, "data_deleteoflist", parent_id=parent_id,
                               inputs={"INDEX": self.expr_to_input(index, bid)},
                               fields={"LIST": [list_name, vid]})
                return [bid]

        # ── My Block call ─────────────────────────────────────────────────
        if obj is None and method in self.procedures:
            proc_info = self.procedures[method]
            arg_ids    = proc_info["arg_ids"]
            proccode   = proc_info["proccode"]
            inputs = {}
            for i, arg_id in enumerate(arg_ids):
                inputs[arg_id] = self.expr_to_input(args[i] if i < len(args)
                                                    else ast.Constant(value=0), bid)
            mutation = {
                "tagName": "mutation", "children": [],
                "proccode": proccode,
                "argumentids": json.dumps(arg_ids),
                "warp": "false"
            }
            self.blocks[bid] = {
                "opcode": "procedures_call",
                "next": None, "parent": parent_id,
                "inputs": inputs, "fields": {},
                "shadow": False, "topLevel": False,
                "mutation": mutation
            }
            return [bid]

        # Skip known non-block calls silently
        if obj in ("hub", "print") or (obj is None and method in ("print",)):
            return []
        if method in ("PrimeHub", "MotorGroup", "Motor", "ColorSensor",
                      "DistanceSensor", "ForceSensor"):
            return []

        self.warnings.append(f"Unsupported call '{obj}.{method}' — skipped")
        return []

    # ─── body compilation (chain blocks) ────────────────────────────────────

    def compile_body(self, body_nodes, parent_id):
        all_ids = []
        for node in body_nodes:
            ids = self.compile_stmt(node, parent_id)
            all_ids.extend(ids)
        # Chain next/parent
        for i in range(len(all_ids) - 1):
            self.blocks[all_ids[i]]["next"] = all_ids[i + 1]
        for i in range(1, len(all_ids)):
            curr = self.blocks[all_ids[i]]
            if curr["parent"] == parent_id:
                curr["parent"] = all_ids[i - 1]
        return all_ids

    # ─── utility ────────────────────────────────────────────────────────────

    def _call_parts(self, node):
        if isinstance(node.func, ast.Attribute):
            val = node.func.value
            method = node.func.attr
            if isinstance(val, ast.Name):
                obj = val.id
            else:
                obj = None
        elif isinstance(node.func, ast.Name):
            obj, method = None, node.func.id
        else:
            obj, method = None, "unknown"
        args   = node.args
        kwargs = {kw.arg: kw.value for kw in node.keywords}
        return obj, method, args, kwargs

    # ─── main compile ────────────────────────────────────────────────────────

    def compile(self, python_code, orig_proj=None):
        tree = ast.parse(python_code)

        # Extract original coordinates and proccodes if available
        orig_coords = {}
        orig_proccodes = {}
        orig_params = {}
        orig_main_coords = (100, 100)
        if orig_proj:
            try:
                # Find all definitions and prototypes
                blocks_dict = orig_proj["targets"][1]["blocks"]
                for bid, b in blocks_dict.items():
                    if isinstance(b, dict) and b.get("opcode") == "procedures_definition":
                        x = b.get("x", 100)
                        y = b.get("y", 100)
                        custom_block_id = b["inputs"]["custom_block"][1]
                        proto_block = blocks_dict.get(custom_block_id)
                        if proto_block:
                            proccode = proto_block["mutation"]["proccode"]
                            import re, unicodedata
                            clean_name = clean_identifier(re.sub(r'%[snb]', '', proccode).strip())
                            clean_name_norm = unicodedata.normalize('NFKC', clean_name)
                            orig_coords[clean_name_norm] = (x, y)
                            orig_proccodes[clean_name_norm] = proccode
                            try:
                                arg_names_list = json.loads(proto_block["mutation"].get("argumentnames", "[]"))
                                param_map = {}
                                for arg in arg_names_list:
                                    clean_arg = clean_identifier(arg)
                                    param_map[clean_arg] = arg
                                orig_params[clean_name_norm] = param_map
                            except Exception:
                                pass
                    elif isinstance(b, dict) and b.get("opcode") == "flipperevents_whenProgramStarts" and b.get("topLevel"):
                        orig_main_coords = (b.get("x", 100), b.get("y", 100))
            except Exception:
                pass

        self.orig_coords = orig_coords
        self.orig_main_coords = orig_main_coords

        # Pass 1: collect procedure signatures
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name != "main":
                arg_names = [a.arg for a in node.args.args]
                arg_ids   = [gen_id() for _ in arg_names]

                # Check if we have the original proccode
                import unicodedata
                node_name_norm = unicodedata.normalize('NFKC', node.name)

                # Retrieve original parameter names if available
                param_map = orig_params.get(node_name_norm, {})
                display_arg_names = [param_map.get(name, name) for name in arg_names]

                if node_name_norm in orig_proccodes:
                    proccode = orig_proccodes[node_name_norm]
                else:
                    proccode  = (node.name + " " +
                                 " ".join("%s" for _ in arg_names)).strip()

                self.procedures[node.name] = {
                    "arg_ids":   arg_ids,
                    "arg_names": arg_names,
                    "display_arg_names": display_arg_names,
                    "proccode":  proccode,
                }



        # Pass 2: collect top-level variables and detect list variables
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        self.add_var(t.id)
            elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
                self.add_var(node.target.id)

            # Detect lists:
            # 1) Call on attribute: mylist.append, mylist.insert, pop, remove
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in ("append", "insert", "pop", "remove"):
                    if isinstance(node.func.value, ast.Name):
                        self.list_names.add(node.func.value.id)
            # 2) Subscript access: mylist[i]
            if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
                self.list_names.add(node.value.id)
            # 3) len(mylist)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "len":
                if node.args and isinstance(node.args[0], ast.Name):
                    self.list_names.add(node.args[0].id)
            # 4) item in mylist
            if isinstance(node, ast.Compare):
                for op in node.ops:
                    if isinstance(op, ast.In):
                        for cmp in node.comparators:
                            if isinstance(cmp, ast.Name):
                                self.list_names.add(cmp.id)

        x_off, y_off = 100, 100


        # Compile function definitions
        for node in tree.body:
            if not (isinstance(node, ast.FunctionDef) and node.name != "main"):
                continue
            func_name = node.name
            if func_name not in self.procedures:
                continue
            proc_info  = self.procedures[func_name]
            arg_ids    = proc_info["arg_ids"]
            arg_names  = proc_info["arg_names"]
            proccode   = proc_info["proccode"]

            def_bid   = gen_id()
            proto_bid = gen_id()

            # Argument reporter shadow blocks
            proto_inputs = {}
            display_arg_names = proc_info.get("display_arg_names", arg_names)
            for arg_id, clean_name, disp_name in zip(arg_ids, arg_names, display_arg_names):
                rep_bid = gen_id()
                self.blocks[rep_bid] = {
                    "opcode": "argument_reporter_string_number",
                    "next": None, "parent": proto_bid,
                    "inputs": {}, "fields": {"VALUE": [disp_name, None]},
                    "shadow": True, "topLevel": False,
                }
                proto_inputs[arg_id] = [1, rep_bid]

            self.blocks[proto_bid] = {
                "opcode": "procedures_prototype",
                "next": None, "parent": def_bid,
                "inputs": proto_inputs, "fields": {},
                "shadow": True, "topLevel": False,
                "mutation": {
                    "tagName": "mutation", "children": [],
                    "proccode": proccode,
                    "argumentids":      json.dumps(arg_ids),
                    "argumentnames":    json.dumps(display_arg_names),
                    "argumentdefaults": json.dumps(["" for _ in display_arg_names]),
                    "warp": "false",
                }
            }

            import unicodedata
            func_name_norm = unicodedata.normalize('NFKC', func_name)
            px, py = self.orig_coords.get(func_name_norm, (x_off, y_off))
            self.blocks[def_bid] = {
                "opcode": "procedures_definition",
                "next": None, "parent": None,
                "inputs": {"custom_block": [1, proto_bid]},
                "fields": {}, "shadow": False, "topLevel": True,
                "x": px, "y": py,
            }
            if func_name_norm not in self.orig_coords:
                y_off += 350


            self.curr_func = func_name
            body_nodes = [n for n in node.body
                          if not isinstance(n, (ast.Global, ast.Return))]
            body_ids = self.compile_body(body_nodes, def_bid)
            if body_ids:
                self.blocks[def_bid]["next"] = body_ids[0]
                self.blocks[body_ids[0]]["parent"] = def_bid
            self.curr_func = None

        # Compile main / top-level
        main_found = False
        main_x, main_y = self.orig_main_coords
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "main":
                main_found = True
                ev_bid = gen_id()
                self.add_block(ev_bid, "flipperevents_whenProgramStarts",
                               top_level=True, x=main_x, y=main_y)
                body_nodes = [n for n in node.body
                              if not isinstance(n, (ast.Global, ast.Return))]
                body_ids = self.compile_body(body_nodes, ev_bid)
                if body_ids:
                    self.blocks[ev_bid]["next"] = body_ids[0]
                    self.blocks[body_ids[0]]["parent"] = ev_bid
                break

        if not main_found:
            top_stmts = [n for n in tree.body
                         if not isinstance(n, (ast.Import, ast.ImportFrom,
                                               ast.FunctionDef))]
            if top_stmts:
                ev_bid = gen_id()
                self.add_block(ev_bid, "flipperevents_whenProgramStarts",
                               top_level=True, x=main_x, y=main_y)
                body_ids = self.compile_body(top_stmts, ev_bid)
                if body_ids:
                    self.blocks[ev_bid]["next"] = body_ids[0]
                    self.blocks[body_ids[0]]["parent"] = ev_bid


        return self.blocks, self.variables, self.warnings


# ─── package to .llsp3 (Word Blocks) ────────────────────────────────────────

def recompile_python_to_wordblocks(input_llsp3_path, output_llsp3_path):
    try:
        # Read Python source and original metadata from .llsp3 (Python)
        orig_manifest = None
        orig_monitors = None
        orig_icon = None
        orig_scratch_bytes = None

        with zipfile.ZipFile(input_llsp3_path, "r") as z:
            names = z.namelist()
            if "projectbody.json" in names:
                body = json.loads(z.read("projectbody.json"))
                python_code = body.get("main", "")
            else:
                return False, "ไม่พบ projectbody.json — อาจไม่ใช่ไฟล์ Python llsp3"
            
            if "orig_manifest.json" in names:
                orig_manifest = json.loads(z.read("orig_manifest.json"))
            if "orig_monitors.json" in names:
                orig_monitors = z.read("orig_monitors.json")
            if "orig_icon.svg" in names:
                orig_icon = z.read("orig_icon.svg")
            if "orig_scratch.sb3" in names:
                orig_scratch_bytes = z.read("orig_scratch.sb3")

        # Use original project.json as base if available
        orig_proj = None
        other_sb3_files = {}
        if orig_scratch_bytes:
            try:
                with zipfile.ZipFile(io.BytesIO(orig_scratch_bytes), "r") as s:
                    for sname in s.namelist():
                        if sname == "project.json":
                            orig_proj = json.loads(s.read(sname))
                        else:
                            other_sb3_files[sname] = s.read(sname)
            except Exception:
                pass

        rc = Recompiler()
        blocks, variables, warnings = rc.compile(python_code, orig_proj=orig_proj)

        # Build Scratch project.json
        var_entries = {}
        list_entries = {}
        for name, vid in variables.items():
            if name in rc.list_names:
                list_entries[vid] = [name, []]
            else:
                var_entries[vid] = [name, 0]


        if orig_proj:
            project = orig_proj
            # Replace target blocks, variables, and lists
            sprite_target = None
            for t in project["targets"]:
                if not t.get("isStage"):
                    sprite_target = t
                    break
            if sprite_target:
                sprite_target["variables"] = var_entries
                sprite_target["lists"] = list_entries
                sprite_target["blocks"] = blocks
        else:
            costume = {
                "name": "costume1",
                "bitmapResolution": 1,
                "dataFormat": "svg",
                "assetId": "d41d8cd98f00b204e9800998ecf8427e",
                "md5ext": "d41d8cd98f00b204e9800998ecf8427e.svg",
                "rotationCenterX": 0,
                "rotationCenterY": 0
            }
            project = {
                "targets": [
                    {
                        "isStage": True,
                        "name": "Stage",
                        "variables": {}, "lists": {}, "broadcasts": {}, "blocks": {},
                        "comments": {}, "currentCostume": 0,
                        "costumes": [costume], "sounds": [],
                        "volume": 100, "layerOrder": 0,
                        "tempo": 60, "videoTransparency": 50,
                        "videoState": "on", "textToSpeechLanguage": None
                    },
                    {
                        "isStage": False,
                        "name": "Sprite1",
                        "variables": var_entries,
                        "lists": list_entries,
                        "broadcasts": {},
                        "blocks": blocks,
                        "comments": {}, "currentCostume": 0,
                        "costumes": [costume], "sounds": [],
                        "volume": 100, "layerOrder": 1,
                        "visible": True,
                        "x": 0,
                        "y": 0,
                        "size": 100,
                        "direction": 90,
                        "draggable": False,
                        "rotationStyle": "all around"
                    }
                ],
                "monitors": [],
                "extensions": [
                    "flippermove", "flippermotor", "flippermoremotor",
                    "flippermoremove", "flippersensors", "flippercontrol",
                    "flipperevents", "flipperdisplay", "flippersound"
                ],
                "meta": {
                    "semver": "3.0.0",
                    "vm": "1.2.58",
                    "agent": ""
                }
            }

        # Pack scratch.sb3
        sb3_buf = io.BytesIO()
        with zipfile.ZipFile(sb3_buf, "w", zipfile.ZIP_DEFLATED) as sb3_zip:
            sb3_zip.writestr("project.json", json.dumps(project))
            # Write other assets back
            for sname, sdata in other_sb3_files.items():
                sb3_zip.writestr(sname, sdata)
            # Ensure blank svg is there if no assets were extracted
            if "d41d8cd98f00b204e9800998ecf8427e.svg" not in other_sb3_files and not orig_proj:
                sb3_zip.writestr("d41d8cd98f00b204e9800998ecf8427e.svg", "")
        sb3_bytes = sb3_buf.getvalue()

        # Manifest
        project_name = os.path.splitext(os.path.basename(output_llsp3_path))[0]
        now_str = datetime.datetime.utcnow().isoformat(timespec='milliseconds') + "Z"
        
        if orig_manifest:
            manifest = orig_manifest
            manifest["name"] = project_name
            manifest["lastsaved"] = now_str
        else:
            pid = gen_id(length=12)
            manifest = {
                "type": "word-blocks",
                "autoDelete": False,
                "created": now_str,
                "id": pid,
                "lastsaved": now_str,
                "size": 0,
                "name": project_name,
                "slotIndex": 0,
                "workspaceX": 120,
                "workspaceY": 120,
                "zoomLevel": 0.5,
                "hardware": {},
                "state": {
                    "playMode": "download",
                    "canvasDrawerOpen": False
                },
                "extraFiles": [],
                "lastConnectedHubType": "flipper"
            }

        if orig_icon:
            icon_svg = orig_icon
        else:
            icon_svg = ('<svg width="60" height="60" xmlns="http://www.w3.org/2000/svg">'
                        '<rect width="60" height="60" rx="8" fill="#F3BD41"/>'
                        '<text x="30" y="38" font-size="24" text-anchor="middle" fill="#1A1A1A">⬛</text>'
                        '</svg>').encode('utf-8')

        if orig_monitors:
            monitors_json = orig_monitors
        else:
            monitors_json = json.dumps([]).encode('utf-8')

        with zipfile.ZipFile(output_llsp3_path, "w", zipfile.ZIP_DEFLATED) as out_zip:
            out_zip.writestr("manifest.json", json.dumps(manifest, indent=2))
            out_zip.writestr("scratch.sb3", sb3_bytes)
            # Write icon and monitors (write accepts bytes or string)
            out_zip.writestr("icon.svg", icon_svg)
            out_zip.writestr("monitors.json", monitors_json)

        return True, warnings


    except SyntaxError as e:
        return False, [f"Syntax Error ในโค้ด Python: {e}"]
    except Exception as e:
        import traceback
        return False, [str(e), traceback.format_exc()]
