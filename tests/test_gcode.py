import math

from creality_killer.core.gcode import parse_gcode

SQUARE = """\
G90
M83
;LAYER_CHANGE
;Z:0.2
;TYPE:Outer wall
G1 X0 Y0 Z0.2 F3000
G1 X10 Y0 E0.5
G1 X10 Y10 E0.5
;TYPE:Infill
G1 X0 Y10 E0.5
G0 X50 Y50 ; travel, no E
;LAYER_CHANGE
;Z:0.4
;TYPE:Outer wall
G1 X0 Y0 Z0.4
G1 X10 Y0 E0.5
"""


def test_markers_layers_and_kinds():
    tp = parse_gcode(SQUARE)
    assert len(tp.segments) == 4  # travel moves dropped
    assert tp.n_layers == 2
    assert tp.layer.tolist() == [0, 0, 0, 1]
    assert [tp.kinds[k] for k in tp.kind] == ["Outer wall", "Outer wall", "Infill", "Outer wall"]
    assert tp.layer_z == [0.2, 0.4]
    assert tp.layer_start.tolist() == [0, 3, 4]


def test_z_based_layers_without_markers():
    src = "G1 X0 Y0 Z0.2\nG1 X5 E1\nG1 Z0.4\nG1 X0 E1\n"
    tp = parse_gcode(src.replace("M83", ""))
    # absolute E (M82 default): second E=1 does not increase -> only one extruding move
    assert tp.n_layers == 1
    src = "M83\nG1 X0 Y0 Z0.2\nG1 X5 E1\nG1 Z0.4\nG1 X0 E1\n"
    tp = parse_gcode(src)
    assert tp.n_layers == 2


def test_offsets_map_progress_to_layer():
    data = SQUARE.encode()
    tp = parse_gcode(data)
    second_layer_line = data.index(b"G1 X10 Y0 E0.5", data.index(b"Z:0.4"))
    assert tp.layer_at_offset(second_layer_line) == 1
    assert tp.layer_at_offset(0) == 0
    assert tp.segment_at_offset(-1) == -1


def test_relative_extrusion_and_g92_reset():
    src = "M82\nG92 E0\nG1 X1 E1\nG92 E0\nG1 X2 E1\n"
    assert len(parse_gcode(src).segments) == 2


def test_arc_is_linearised():
    src = "M83\nG1 X10 Y0 Z0.2\nG3 X-10 Y0 I-10 J0 E1\n"  # ccw half circle, r=10
    tp = parse_gcode(src)
    assert len(tp.segments) > 20
    pts = tp.segments[:, 3:5]
    assert all(abs(math.hypot(px, py) - 10) < 0.05 for px, py in pts)
    assert abs(tp.segments[-1, 3] + 10) < 1e-3


def test_empty_file():
    tp = parse_gcode("G28\nM104 S200\n")
    assert len(tp.segments) == 0 and tp.n_layers == 0
