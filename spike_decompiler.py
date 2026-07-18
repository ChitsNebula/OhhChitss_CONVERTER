import zipfile
import json
import io
import re
import os
import random
import string
import datetime

def clean_identifier(name):
    if not name:
        return "var"
    cleaned = re.sub(r'[^a-zA-Z0-9_\u0e00-\u0e7f]', '_', name)
    if cleaned[0].isdigit():
        cleaned = "_" + cleaned
    if cleaned in ("def", "class", "if", "else", "elif", "while", "for", "in", "import", "from", "return", "pass", "and", "or", "not", "is"):
        cleaned = cleaned + "_"
    return cleaned

def s3_port(val):
    """Convert port string like 'A' to port.A for SPIKE 3"""
    s = str(val).strip().strip("'\"")
    if len(s) == 1 and s.upper() in 'ABCDEF':
        return f"port.{s.upper()}"
    return val

def s3_ports_list(val):
    """Convert port string like 'BF' to ['port.B', 'port.F'] for SPIKE 3"""
    s = str(val).strip().strip("'\"")
    if s and all(c.upper() in 'ABCDEF' for c in s):
        return [f"port.{c.upper()}" for c in s]
    return [s3_port(val)]

def generate_random_id(length=12):
    chars = string.ascii_letters + string.digits
    return "".join(random.choice(chars) for _ in range(length))

def decompile_spike_project(llsp3_path, output_llsp3_path):
    try:
        # 1. Parse block code from the source llsp3 (Word Blocks)
        with zipfile.ZipFile(llsp3_path, "r") as z:
            sb3_data = z.read("scratch.sb3")
            names = z.namelist()
            orig_manifest_data = z.read("manifest.json") if "manifest.json" in names else None
            orig_monitors_data = z.read("monitors.json") if "monitors.json" in names else None
            orig_icon_data = z.read("icon.svg") if "icon.svg" in names else None
        
        with zipfile.ZipFile(io.BytesIO(sb3_data), "r") as sb3_zip:

            project = json.loads(sb3_zip.read("project.json"))
            
        target = project["targets"][1]
        blocks = target["blocks"]
        
        var_map = {}
        for var_id, var_info in target.get("variables", {}).items():
            var_map[var_id] = clean_identifier(var_info[0])
        for list_id, list_info in target.get("lists", {}).items():
            var_map[list_id] = clean_identifier(list_info[0])

            
        def resolve(val):
            if not val:
                return "None"
            if isinstance(val, list):
                val_type = val[0]
                if val_type == 12:
                    var_id = val[2]
                    return var_map.get(var_id, clean_identifier(val[1]))
                if val_type == 13:
                    list_id = val[2]
                    return var_map.get(list_id, clean_identifier(val[1]))
                if val_type in (4, 5, 6, 7, 8, 9, 10, 11):
                    lit = val[1]
                    if isinstance(lit, str):
                        try:
                            if "." in lit:
                                float(lit)
                                return lit
                            else:
                                int(lit)
                                return lit
                        except ValueError:
                            return f"'{lit}'"
                    return str(lit)
                if val_type in (1, 2, 3):
                    return resolve(val[1])
                return str(val)
            if isinstance(val, str):
                if val in blocks:
                    return decompile_block(val)
                return f"'{val}'"
            return str(val)

        arg_reporter_map = {}
        for b_id, b in blocks.items():
            if not isinstance(b, dict): continue
            if b.get("opcode") == "argument_reporter_string_number":
                arg_name = b["fields"]["VALUE"][0]
                arg_reporter_map[b_id] = clean_identifier(arg_name)

        def decompile_block(b_id):
            if b_id in arg_reporter_map:
                return arg_reporter_map[b_id]
                
            b = blocks[b_id]
            opcode = b.get("opcode")
            inputs = b.get("inputs", {})
            fields = b.get("fields", {})
            
            def get_in(name, default="None"):
                if name in inputs:
                    return resolve(inputs[name][1])
                return default

            def get_field(name, default="None"):
                if name in fields:
                    return fields[name][0]
                return default

            # Menu/selector/custom shadow blocks → return their field value directly
            field_key = "field_" + opcode
            if field_key in fields:
                return f"'{fields[field_key][0]}'"
            # acceleration menu: field key is 'acceleration'
            if "menu_acceleration" in opcode and "acceleration" in fields:
                return f"'{fields['acceleration'][0]}'"
            # rotation-wheel, custom-piano, colour menus etc.
            # Only apply single-field shortcut to shadow menu/selector blocks
            _MENU_KEYWORDS = ("menu", "selector", "custom-icon", "custom-piano",
                               "rotation-wheel", "color-selector", "colour")
            if (fields and len(fields) == 1 and
                    any(kw in opcode for kw in _MENU_KEYWORDS)):
                only_val = list(fields.values())[0]
                if only_val and only_val[0] is not None:
                    return f"'{only_val[0]}'"


            if opcode == "operator_add":
                return f"({get_in('NUM1')} + {get_in('NUM2')})"
            elif opcode == "operator_subtract":
                return f"({get_in('NUM1')} - {get_in('NUM2')})"
            elif opcode == "operator_multiply":
                return f"({get_in('NUM1')} * {get_in('NUM2')})"
            elif opcode == "operator_divide":
                return f"({get_in('NUM1')} / {get_in('NUM2')})"
            elif opcode == "operator_equals":
                return f"({get_in('OPERAND1')} == {get_in('OPERAND2')})"
            elif opcode == "operator_gt":
                return f"({get_in('OPERAND1')} > {get_in('OPERAND2')})"
            elif opcode == "operator_lt":
                return f"({get_in('OPERAND1')} < {get_in('OPERAND2')})"
            elif opcode == "operator_not":
                return f"(not {get_in('OPERAND')})"
            elif opcode == "operator_and":
                return f"({get_in('OPERAND1')} and {get_in('OPERAND2')})"
            elif opcode == "operator_or":
                return f"({get_in('OPERAND1')} or {get_in('OPERAND2')})"
            elif opcode == "operator_contains":
                return f"({get_in('STRING2')} in {get_in('STRING1')})"
            elif opcode == "operator_mathop":
                op = get_field("OPERATOR")
                # abs is a Python built-in, not math.abs
                if op == "abs":
                    return f"abs({get_in('NUM')})"
                return f"math.{op}({get_in('NUM')})"
            elif opcode == "flipperoperator_isInBetween":
                return f"({get_in('LOW')} <= {get_in('VALUE')} <= {get_in('HIGH')})"

            elif opcode == "flippersensors_reflectivity":
                return f"color_sensor.reflection({s3_port(get_in('PORT'))})"
            elif opcode == "flippersensors_isReflectivity":
                cmp = get_field("COMPARATOR", "<")
                return f"(color_sensor.reflection({s3_port(get_in('PORT'))}) {cmp} {get_in('VALUE')})"
            elif opcode == "flippersensors_isColor":
                return f"color_sensor.color({s3_port(get_in('PORT'))}) == {get_in('COLOR')}"
            elif opcode == "flippersensors_color":
                port_val = get_in('PORT', None)
                if port_val and port_val != 'None':
                    return f"color_sensor.color({s3_port(port_val)})"
                return "color_sensor.color(port.C)"
            elif opcode == "flippersensors_distance":
                return f"distance_sensor.distance({s3_port(get_in('PORT'))})"
            elif opcode == "flippersensors_force":
                return f"force_sensor.force({s3_port(get_in('PORT'))})"
            elif opcode == "flippersensors_isPressed":
                return f"force_sensor.pressed({s3_port(get_in('PORT'))})"

            elif opcode == "flippersensors_orientationAxis":
                axis = get_field("AXIS", "yaw").lower()
                if axis == "yaw":
                    return "hub.motion_sensor.get_yaw_angle()"
                else:
                    idx = {"roll": 0, "pitch": 1}.get(axis, 0)
                    return f"(hub.motion_sensor.tilt_angles()[{idx}] / 10)"
            elif opcode == "flippersensors_tiltAngle":
                return "(hub.motion_sensor.tilt_angles()[0] / 10)"
            elif opcode == "flippersensors_timer":
                return "_timer()"
            elif opcode == "flippersensors_resetTimer":
                return "_timer()"  # expression context — return current timer
            elif opcode == "flippermoremotor_position":
                return f"motor.relative_position({s3_port(get_in('PORT'))})"
            elif opcode == "flippermoremotor_degrees":
                return f"motor.relative_position({s3_port(get_in('PORT'))})"

            elif opcode == "procedures_call":
                proc_code = b["mutation"]["proccode"]
                arg_ids = json.loads(b["mutation"]["argumentids"])
                args = []
                for arg_id in arg_ids:
                    args.append(get_in(arg_id))
                clean_name = clean_identifier(re.sub(r'%[snb]', '', proc_code).strip())
                return f"{clean_name}({', '.join(args)})"
            else:
                return f"False  # unsupported expr: {opcode}"

        def decompile_chain(start_id, indent=0):
            lines = []
            curr_id = start_id
            while curr_id:
                b = blocks[curr_id]
                opcode = b.get("opcode")
                inputs = b.get("inputs", {})
                fields = b.get("fields", {})
                indent_str = "    " * indent
                
                def get_in(name, default="None"):
                    if name in inputs:
                        return resolve(inputs[name][1])
                    return default

                def get_field(name, default="None"):
                    if name in fields:
                        return fields[name][0]
                    return default

                if opcode == "data_setvariableto":
                    var_id = fields["VARIABLE"][1]
                    var_name = var_map.get(var_id, clean_identifier(fields["VARIABLE"][0]))
                    lines.append(f"{indent_str}{var_name} = {get_in('VALUE')}")
                elif opcode == "data_changevariableby":
                    var_id = fields["VARIABLE"][1]
                    var_name = var_map.get(var_id, clean_identifier(fields["VARIABLE"][0]))
                    lines.append(f"{indent_str}{var_name} += {get_in('VALUE')}")

                elif opcode == "flippermove_setMovementPair":
                    pair_raw = str(get_in('PAIR')).strip().strip("'\"")
                    if len(pair_raw) >= 2:
                        p1, p2 = pair_raw[0].upper(), pair_raw[1].upper()
                        lines.append(f"{indent_str}try:")
                        lines.append(f"{indent_str}    motor_pair.unpair(motor_pair.PAIR_1)")
                        lines.append(f"{indent_str}except Exception:")
                        lines.append(f"{indent_str}    pass")
                        lines.append(f"{indent_str}motor_pair.pair(motor_pair.PAIR_1, port.{p1}, port.{p2})")
                    else:
                        lines.append(f"{indent_str}# movement.pair({get_in('PAIR')}) — update ports manually")
                elif opcode == "flippermove_movementSpeed":
                    lines.append(f"{indent_str}# movement.speed({get_in('SPEED')}) — set via motor_pair velocity directly")
                elif opcode == "flippermove_move":
                    lines.append(f"{indent_str}# movement.move({get_in('VALUE')}, unit='{get_field('UNIT')}') — convert to motor_pair.move_for_degrees")
                elif opcode == "flippermove_stopMove":
                    lines.append(f"{indent_str}motor_pair.stop(motor_pair.PAIR_1)")
                elif opcode == "flippermove_steer":
                    lines.append(f"{indent_str}# movement.steer({get_in('STEERING')}, {get_in('VALUE')}) — use motor_pair.move")
                elif opcode == "flippermotor_motorTurnForDirection":
                    direction = str(get_in('DIRECTION')).strip().strip("'\"")
                    sign = "-" if direction == "counterclockwise" else ""
                    val = get_in('VALUE')
                    unit = get_field('UNIT', 'rotations')
                    deg_expr = f"int({val} * 360)" if unit == 'rotations' else str(val)
                    for p in s3_ports_list(get_in('PORT')):
                        lines.append(f"{indent_str}motor.run_for_degrees({p}, {sign}{deg_expr}, 500)")
                elif opcode == "flippermoremove_startDualSpeed":
                    left = get_in('LEFT')
                    right = get_in('RIGHT')
                    lines.append(f"{indent_str}motor_pair.move_tank(motor_pair.PAIR_1, int({left}), int({right}))")
                elif opcode == "flippermoremotor_motorStartPower":
                    for p in s3_ports_list(get_in('PORT')):
                        lines.append(f"{indent_str}motor.run({p}, int({get_in('POWER')} * 10))")
                elif opcode == "flippersensors_resetYaw":
                    lines.append(f"{indent_str}hub.motion_sensor.reset_yaw(0)")
                elif opcode == "flippermoremotor_motorSetDegreeCounted":
                    for p in s3_ports_list(get_in('PORT')):
                        lines.append(f"{indent_str}motor.reset_relative_position({p}, {get_in('VALUE')})")
                elif opcode == "flippermoremotor_motorGoToRelativePosition":
                    spd = get_in('SPEED') if 'SPEED' in inputs else '500'
                    for p in s3_ports_list(get_in('PORT')):
                        lines.append(f"{indent_str}motor.run_for_degrees({p}, {get_in('POSITION')}, int({spd} * 10))")
                elif opcode == "flippermoremotor_motorSetStopMethod":
                    stop_type = get_field("STOP")
                    stop_map = {"0": "coast", "1": "brake", "2": "hold"}
                    stop_label = stop_map.get(str(stop_type), stop_type)
                    lines.append(f"{indent_str}# motor.set_stop_method({s3_port(get_in('PORT'))}, '{stop_label}') — not supported in SPIKE 3")
                elif opcode == "flippermoremotor_motorSetAcceleration":
                    lines.append(f"{indent_str}# motor.set_acceleration({s3_port(get_in('PORT'))}, {get_in('ACCELERATION')}) — not supported in SPIKE 3")
                elif opcode == "flippermoremove_movementSetAcceleration":
                    lines.append(f"{indent_str}# movement.set_acceleration({get_in('ACCELERATION')}) — not supported in SPIKE 3")
                elif opcode == "flippermotor_motorSetSpeed":
                    lines.append(f"{indent_str}# motor.set_speed({s3_port(get_in('PORT'))}, {get_in('SPEED')}) — set speed via motor.run directly")
                elif opcode == "flippersensors_resetTimer":
                    lines.append(f"{indent_str}_reset_timer()")
                elif opcode == "flippermoremotor_menu_acceleration":
                    pass  # shadow menu block, consumed by parent

                elif opcode == "flippersound_beepForTime":
                    lines.append(f"{indent_str}hub.sound.beep(int({get_in('NOTE')}), int({get_in('DURATION')} * 1000))")
                elif opcode == "sound_setvolumeto":
                    lines.append(f"{indent_str}hub.sound.volume(int({get_in('VOLUME')}))")
                elif opcode == "flippercontrol_stop":
                    lines.append(f"{indent_str}raise SystemExit")
                elif opcode == "control_wait":
                    lines.append(f"{indent_str}time.sleep({get_in('DURATION')})")
                elif opcode == "control_wait_until":
                    lines.append(f"{indent_str}# Wait until\n{indent_str}while not {get_in('CONDITION')}:\n{indent_str}    time.sleep(0.01)")
                elif opcode == "control_forever":
                    substack = inputs.get("SUBSTACK", [None, None])[1]
                    lines.append(f"{indent_str}while True:")
                    if substack:
                        lines.append(decompile_chain(substack, indent + 1))
                    else:
                        lines.append(f"{indent_str}    pass")
                elif opcode == "control_repeat_until":
                    cond = get_in("CONDITION")
                    substack = inputs.get("SUBSTACK", [None, None])[1]
                    lines.append(f"{indent_str}while not {cond}:")
                    if substack:
                        lines.append(decompile_chain(substack, indent + 1))
                    else:
                        lines.append(f"{indent_str}    pass")
                elif opcode == "control_repeat":
                    times = get_in("TIMES")
                    substack = inputs.get("SUBSTACK", [None, None])[1]
                    lines.append(f"{indent_str}for _ in range(int({times})):")
                    if substack:
                        lines.append(decompile_chain(substack, indent + 1))
                    else:
                        lines.append(f"{indent_str}    pass")
                elif opcode == "control_if":
                    cond = get_in("CONDITION")
                    substack = inputs.get("SUBSTACK", [None, None])[1]
                    lines.append(f"{indent_str}if {cond}:")
                    if substack:
                        body = decompile_chain(substack, indent + 1)
                        lines.append(body)
                        # If body contains ONLY comments, add pass to keep syntax valid
                        body_lines = [l.strip() for l in body.split('\n') if l.strip()]
                        if all(l.startswith('#') for l in body_lines):
                            lines.append(f"{indent_str}    pass")
                    else:
                        lines.append(f"{indent_str}    pass")

                elif opcode == "control_if_else":
                    cond = get_in("CONDITION")
                    substack = inputs.get("SUBSTACK", [None, None])[1]
                    substack2 = inputs.get("SUBSTACK2", [None, None])[1]
                    lines.append(f"{indent_str}if {cond}:")
                    if substack:
                        lines.append(decompile_chain(substack, indent + 1))
                    else:
                        lines.append(f"{indent_str}    pass")
                    lines.append(f"{indent_str}else:")
                    if substack2:
                        lines.append(decompile_chain(substack2, indent + 1))
                    else:
                        lines.append(f"{indent_str}    pass")
                elif opcode == "flippersensors_resetTimer":
                    pass  # reset timer — no Python equivalent, skip
                elif opcode == "flippersensors_isReflectivity":
                    # inline reflectivity comparison — output as comment + pass
                    lines.append(f"{indent_str}# flippersensors_isReflectivity (unsupported — skipped)")
                    lines.append(f"{indent_str}pass")
                elif opcode == "procedures_call":
                    lines.append(f"{indent_str}{decompile_block(curr_id)}")
                else:
                    lines.append(f"{indent_str}# Unsupported Statement Opcode: {opcode}")
                    lines.append(f"{indent_str}pass")
                curr_id = b.get("next")
            return "\n".join(lines)

        output = []
        output.append("# Translated SPIKE Prime Python Code (SPIKE 3.x API)")
        output.append("import hub")
        output.append("import runloop")
        output.append("import motor")
        output.append("import motor_pair")
        output.append("import color_sensor")
        output.append("import distance_sensor")
        output.append("import force_sensor")
        output.append("import time")
        output.append("import math")
        output.append("from hub import port")
        output.append("")
        output.append("# Timer helpers (replaces SPIKE 2.x sensors.timer)")
        output.append("_timer_start = time.ticks_ms()")
        output.append("")
        output.append("def _reset_timer():")
        output.append("    global _timer_start")
        output.append("    _timer_start = time.ticks_ms()")
        output.append("")
        output.append("def _timer():")
        output.append("    return time.ticks_diff(time.ticks_ms(), _timer_start) / 1000.0")
        output.append("")

        global_vars = [clean_identifier(v[0]) for v in target.get("variables", {}).values()]
        if global_vars:
            output.append("# Global Variables")
            for g_var in global_vars:
                output.append(f"{g_var} = 0")
            output.append("")

        for b_id, b in blocks.items():
            if not isinstance(b, dict): continue
            if b.get("opcode") == "procedures_definition":
                proto_id = b["inputs"]["custom_block"][1]
                proto = blocks[proto_id]
                proc_code = proto["mutation"]["proccode"]
                arg_names = [clean_identifier(name) for name in json.loads(proto["mutation"]["argumentnames"])]
                clean_name = clean_identifier(re.sub(r'%[snb]', '', proc_code).strip())
                output.append(f"def {clean_name}({', '.join(arg_names)}):")
                # Filter out parameter names from global declaration to avoid SyntaxError
                filtered_globals = [g for g in global_vars if g not in arg_names]
                if filtered_globals:
                    output.append(f"    global {', '.join(filtered_globals)}")
                body_start_id = b.get("next")
                if body_start_id:
                    output.append(decompile_chain(body_start_id, indent=1))
                else:
                    output.append("    pass")
                output.append("")

        main_start_id = None
        for b_id, b in blocks.items():
            if not isinstance(b, dict): continue
            if b.get("opcode") == "flipperevents_whenProgramStarts":
                main_start_id = b.get("next")
                break
                
        if main_start_id:
            output.append("# Main Program")
            output.append("def main():")
            if global_vars:
                output.append(f"    global {', '.join(global_vars)}")
            output.append(decompile_chain(main_start_id, indent=1))
            output.append("")
            output.append("if __name__ == '__main__':")
            output.append("    main()")
            
        python_code = "\n".join(output)

        # 2. Package python code into a new SPIKE Prime Python Project (.llsp3 format)
        project_name = os.path.splitext(os.path.basename(output_llsp3_path))[0]
        now_str = datetime.datetime.utcnow().isoformat(timespec='milliseconds') + "Z"
        project_id = generate_random_id()
        
        manifest = {
            "type": "python",
            "appType": "llsp3",
            "autoDelete": False,
            "created": now_str,
            "id": project_id,
            "lastsaved": now_str,
            "size": 0,
            "name": project_name,
            "slotIndex": 0,
            "workspaceX": 120,
            "workspaceY": 120,
            "zoomLevel": 0.5,
            "hardware": {
                "python": {
                    "type": "flipper"
                }
            },
            "state": {
                "canvasDrawerOpen": True,
                "canvasDrawerTab": "monitorTab"
            },
            "extraFiles": []
        }
        
        projectbody = {
            "main": python_code
        }
        
        icon_svg = '<svg width="60" height="60" xmlns="http://www.w3.org/2000/svg"><g fill="none" fill-rule="evenodd"><g fill="#D8D8D8" fill-rule="nonzero"><path d="M34.613 7.325H15.79a3.775 3.775 0 00-3.776 3.776v37.575a3.775 3.775 0 003.776 3.776h28.274a3.775 3.775 0 003.776-3.776V20.714a.8.8 0 00-.231-.561L35.183 7.563a.8.8 0 00-.57-.238zm-.334 1.6l11.96 12.118v27.633a2.175 2.175 0 01-2.176 2.176H15.789a2.175 2.175 0 01-2.176-2.176V11.1c0-1.202.973-2.176 2.176-2.176h18.49z"/><path d="M35.413 8.214v11.7h11.7v1.6h-13.3v-13.3z"/></g><path fill="#0290F5" d="M23.291 27h13.5v2.744h-13.5z"/><path fill="#D8D8D8" d="M38.428 27h4.32v2.744h-4.32zM17 27h2.7v2.7H17zM17 31.86h2.7v2.744H17zM28.151 31.861h11.34v2.7h-11.34zM17 36.72h2.7v2.7H17zM34.665 36.723h8.1v2.7h-8.1z"/><path fill="#0290F5" d="M28.168 36.723h4.86v2.7h-4.86z"/></g></svg>'
        
        # Write to zip file
        with zipfile.ZipFile(output_llsp3_path, "w", zipfile.ZIP_DEFLATED) as out_zip:
            out_zip.writestr("manifest.json", json.dumps(manifest, indent=2))
            out_zip.writestr("projectbody.json", json.dumps(projectbody, indent=2))
            out_zip.writestr("icon.svg", icon_svg)
            
            # Save original Word Blocks project files inside the python llsp3
            if orig_manifest_data:
                out_zip.writestr("orig_manifest.json", orig_manifest_data)
            if orig_monitors_data:
                out_zip.writestr("orig_monitors.json", orig_monitors_data)
            if orig_icon_data:
                out_zip.writestr("orig_icon.svg", orig_icon_data)
            if sb3_data:
                out_zip.writestr("orig_scratch.sb3", sb3_data)
            
        return True, "OK"

    except Exception as e:
        return False, str(e)
