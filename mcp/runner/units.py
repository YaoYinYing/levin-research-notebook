"""Dimensional (unit) checking for recorded quantities.

The point is not to convert values but to catch the failure a reader cannot see:
`rmsd = 2.1` with no unit, `temperature` recorded in ps, the same quantity given
in nm in one run and Å in another, or an uncertainty carrying a different unit
from its value. Everything here is arithmetic on dimensions, so it needs no
network and no unit database beyond the table below.

A quantity is `{name, value, unit, uncertainty?, note?}`. `check()` returns
explicit issues; it never guesses silently and never rewrites the value.
"""
from __future__ import annotations

import math
import re

# Base dimensions: length, time, mass, amount, temperature, angle, charge.
BASE = ("L", "T", "M", "N", "TH", "A", "Q")

# SI-referenced primaries. Factor is the multiplier to the SI base unit.
_UNITS = {
    # length -> m
    "m": {"L": 1}, "cm": {"L": 1}, "mm": {"L": 1}, "um": {"L": 1}, "nm": {"L": 1},
    "pm": {"L": 1}, "fm": {"L": 1}, "A": {"L": 1},
    # time -> s
    "s": {"T": 1}, "ms": {"T": 1}, "us": {"T": 1}, "ns": {"T": 1}, "ps": {"T": 1},
    "fs": {"T": 1}, "min": {"T": 1}, "h": {"T": 1}, "hr": {"T": 1}, "d": {"T": 1},
    "day": {"T": 1},
    # mass -> kg
    "kg": {"M": 1}, "g": {"M": 1}, "mg": {"M": 1}, "ug": {"M": 1}, "Da": {"M": 1},
    "kDa": {"M": 1}, "amu": {"M": 1},
    # amount -> mol
    "mol": {"N": 1}, "mmol": {"N": 1}, "umol": {"N": 1}, "nmol": {"N": 1},
    # temperature -> K (offsets are not applied; see AFFINE)
    "K": {"TH": 1}, "C": {"TH": 1}, "F": {"TH": 1},
    # angle -> rad
    "rad": {"A": 1}, "deg": {"A": 1}, "degree": {"A": 1},
    # charge -> C
    "e": {"Q": 1}, "C_charge": {"Q": 1},
    # energy -> J
    "J": {"M": 1, "L": 2, "T": -2}, "kJ": {"M": 1, "L": 2, "T": -2},
    "cal": {"M": 1, "L": 2, "T": -2}, "kcal": {"M": 1, "L": 2, "T": -2},
    "eV": {"M": 1, "L": 2, "T": -2}, "hartree": {"M": 1, "L": 2, "T": -2},
    # pressure -> Pa
    "Pa": {"M": 1, "L": -1, "T": -2}, "kPa": {"M": 1, "L": -1, "T": -2},
    "MPa": {"M": 1, "L": -1, "T": -2}, "bar": {"M": 1, "L": -1, "T": -2},
    "atm": {"M": 1, "L": -1, "T": -2}, "torr": {"M": 1, "L": -1, "T": -2},
    # dimensionless scales
    "percent": {"_scale": 0.01}, "ppm": {"_scale": 1e-6}, "count": {}, "frame": {},
    "unitless": {}, "dimensionless": {},
}

_FACTORS = {
    "m": 1.0, "cm": 1e-2, "mm": 1e-3, "um": 1e-6, "nm": 1e-9, "pm": 1e-12,
    "fm": 1e-15, "A": 1e-10, "angstrom": 1e-10,
    "s": 1.0, "ms": 1e-3, "us": 1e-6, "ns": 1e-9, "ps": 1e-12, "fs": 1e-15,
    "min": 60.0, "h": 3600.0, "hr": 3600.0, "d": 86400.0, "day": 86400.0,
    "kg": 1.0, "g": 1e-3, "mg": 1e-6, "ug": 1e-9, "Da": 1.66053906660e-27,
    "kDa": 1.66053906660e-24, "amu": 1.66053906660e-27,
    "mol": 1.0, "mmol": 1e-3, "umol": 1e-6, "nmol": 1e-9,
    "K": 1.0, "C": 1.0, "F": 1.0,
    "rad": 1.0, "deg": math.pi / 180.0, "degree": math.pi / 180.0,
    "e": 1.602176634e-19, "C_charge": 1.0,
    "J": 1.0, "kJ": 1e3, "cal": 4.184, "kcal": 4184.0, "eV": 1.602176634e-19,
    "hartree": 4.3597447222071e-18,
    "Pa": 1.0, "kPa": 1e3, "MPa": 1e6, "bar": 1e5, "atm": 101325.0, "torr": 133.322,
    "percent": 0.01, "ppm": 1e-6, "count": 1.0, "frame": 1.0,
    "unitless": 1.0, "dimensionless": 1.0,
}

# Celsius/Fahrenheit are affine, so a plain factor would be a lie. They are
# accepted for dimension checking but flagged as non-convertible.
AFFINE = {"C": "°C", "F": "°F"}

_SUPERS = {"⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5",
           "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9", "⁻": "-", "⁺": "+"}
_SUPERS_RE = re.compile("([" + "".join(_SUPERS) + "]+)")

_TOKEN = re.compile(r"^([A-Za-z%µμÅ°Ω]+)(?:\^?([+-]?\d+))?$")

# Spellings that mean the same thing; mapped before tokenising so the dimension
# table stays one entry per physical unit.
_UNIT_ALIASES = {
    "°": "deg", "degree": "deg", "degrees": "deg",
    "%": "percent", "percent": "percent",
    "fraction": "", "ratio": "", "unitless": "", "dimensionless": "",
    "frames": "frame", "帧": "frame",
    "å": "A", "angstroms": "A", "ångström": "A",
    "sec": "s", "second": "s", "seconds": "s",
    "hour": "h", "hours": "h", "days": "d",
}

# Per-quantity expectations. `family` names are matched against the quantity name.
FAMILIES = {
    "length": {"dims": {"L": 1}, "preferred": "Å", "aliases": (
        "distance", "dist", "length", "rmsd", "rms", "rg", "radius_of_gyration",
        "gyrate", "thickness", "diameter", "bond", "hbond", "h_bond", "cutoff",
        "displacement", "rmsf", "sasa_thickness")},
    "time": {"dims": {"T": 1}, "preferred": "ns", "aliases": (
        "time", "duration", "dt", "timestep", "tau", "trajectory_length",
        "equilibration", "production", "sampling_time", "correlation_time")},
    "mass": {"dims": {"M": 1}, "preferred": "Da", "aliases": ("mass", "mw", "weight")},
    "amount": {"dims": {"N": 1}, "preferred": "mol", "aliases": ("amount", "moles", "concentration_molar")},
    "temperature": {"dims": {"TH": 1}, "preferred": "K", "aliases": (
        "temperature", "temp", "t", "thermostat_temperature", "target_temperature")},
    "molar_energy": {"dims": {"M": 1, "L": 2, "T": -2, "N": -1}, "preferred": "kJ/mol",
                     "aliases": ("energy", "delta_g", "dg", "free_energy", "enthalpy",
                                 "potential_energy", "binding_energy", "activation_energy",
                                 "ea", "mm_pbsa", "delta_e")},
    "force": {"dims": {"M": 1, "L": 1, "T": -2, "N": -1}, "preferred": "kJ/mol/nm",
              "aliases": ("force", "mean_force", "pull_force")},
    # A harmonic restraint constant carries one more inverse length than a force:
    # kJ/(mol·nm²), which is what `restraint_k` means in GROMACS and what a spring
    # constant means in any other engine. Keeping it separate is the whole point of
    # checking dimensions instead of trusting the label.
    "force_constant": {"dims": {"M": 1, "T": -2, "N": -1}, "preferred": "kJ/mol/nm2",
                       "aliases": ("force_constant", "restraint_k", "k_spring", "spring_constant")},
    "pressure": {"dims": {"M": 1, "L": -1, "T": -2}, "preferred": "bar",
                 "aliases": ("pressure", "p", "ref_p", "barostat_pressure")},
    "area": {"dims": {"L": 2}, "preferred": "Å²", "aliases": ("area", "sasa", "asa", "surface_area", "cross_section")},
    "volume": {"dims": {"L": 3}, "preferred": "Å³", "aliases": ("volume", "vol", "pocket_volume", "box_volume")},
    "density": {"dims": {"M": 1, "L": -3}, "preferred": "g/cm³", "aliases": ("density", "rho")},
    "rate": {"dims": {"T": -1}, "preferred": "1/s",
             "aliases": ("rate", "rate_constant", "k", "k_rate", "frequency", "freq", "turnover")},
    "velocity": {"dims": {"L": 1, "T": -1}, "preferred": "nm/ns", "aliases": ("velocity", "speed", "drift")},
    "angle": {"dims": {"A": 1}, "preferred": "°", "aliases": ("angle", "theta", "phi", "psi", "torsion", "dihedral", "attack_angle")},
    "fraction": {"dims": {}, "preferred": "%", "aliases": (
        "fraction", "occupancy", "percentage", "percent", "ratio", "helix_fraction",
        "coverage", "ss_fraction", "plddt_mean")},
}

# Tolerance for comparing a recorded factor to the preferred one: the same
# dimension in a different but legal unit is a warning, not an error.
_UNIT_SCALE_TOL = 0.02


def _normalise(text: str) -> str:
    raw = str(text or "").strip()
    raw = raw.replace("·", " ").replace("⋅", " ").replace("*", " ").replace("×", " ")
    raw = raw.replace("μ", "u").replace("µ", "u")
    raw = raw.replace("°C", "C").replace("°F", "F").replace("°", "deg")
    raw = _SUPERS_RE.sub(lambda m: "^" + "".join(_SUPERS[ch] for ch in m.group(1)), raw)
    raw = re.sub(r"\s*/\s*", "/", raw)
    raw = re.sub(r"\s+", " ", raw)
    return raw.strip()


def _canonical_unit_name(token: str) -> str:
    if token in ("A", "angstrom", "Å"):
        return "A"
    return token


def parse_unit(text: str) -> tuple[dict[str, int], float]:
    """Return (dimension exponents, factor to SI). Raises ValueError if unknown.

    Accepts the spellings that appear in real records: `Å`, `A`, `nm`, `ps`,
    `kJ/mol`, `kcal·mol⁻¹`, `kJ mol-1 nm-2`, `s^-1`, `g/cm3`, `ns/day`.
    """
    if text is None:
        raise ValueError("缺单位")
    raw = _normalise(text)
    if raw in ("", "1", "-"):
        return {}, 1.0
    raw = raw.replace("Å", "A").replace("Å", "A")
    numerator, *denominators = raw.split("/")
    if any(part.strip() == "" for part in [numerator, *denominators]) and raw.strip() not in ("", "1"):
        raise ValueError(f"空的分子或分母：{text!r}")
    dims: dict[str, int] = {}
    factor = 1.0

    def apply(part: str, sign: int) -> None:
        nonlocal factor
        part = part.strip()
        if not part or part in ("1", ""):
            return
        for token in part.split(" "):
            if not token:
                continue
            match = _TOKEN.match(token)
            if not match:
                raise ValueError(f"无法解析的单位片段：{token}")
            name, exponent = match.group(1), match.group(2)
            name = _UNIT_ALIASES.get(name, name)
            exponent = int(exponent) if exponent else 1
            if name == "":
                return
            # `A` is Å in structural records but also ampere; the table has no
            # ampere, so an `A` here is unambiguous.
            if name not in _UNITS:
                raise ValueError(f"未知单位：{name}")
            scale = _FACTORS.get(name, 1.0)
            if name in AFFINE:
                # Affine scales only matter for conversion, which this module
                # does not perform; flag it so the report can say so.
                scale = 1.0
            for dim, power in _UNITS[name].items():
                if dim == "_scale":
                    factor *= scale ** (exponent * sign)
                    continue
                dims[dim] = dims.get(dim, 0) + power * exponent * sign
            if "_scale" not in _UNITS[name]:
                factor *= scale ** (exponent * sign)

    apply(numerator, 1)
    for part in denominators:
        apply(part, -1)
    dims = {k: v for k, v in dims.items() if v}
    return dims, factor


_DIM_SYMBOL = {"L": "L", "T": "T", "M": "M", "N": "N", "TH": "TH", "TEMP": "TH",
               "A": "A", "Q": "Q"}
_DIM_TOKEN = re.compile(r"^([A-Za-z]+)(?:\^?([+-]?\d+))?$")


def parse_dimension(text: str) -> dict[str, int]:
    """Parse a dimension formula such as `L`, `L^2`, `M L^2 T^-2 N^-1`.

    Deliberately separate from `parse_unit`: `L` is a dimension symbol, not a unit
    name, so a caller declaring dimension="L" for `d_attack` must not be told their
    declaration is unparsable.
    """
    raw = " ".join(str(text or "").replace("\u00b7", " ").replace("*", " ").split())
    if not raw or raw in ("1", "dimensionless", "\u65e0\u91cf\u7eb2"):
        return {}
    dims: dict[str, int] = {}
    for token in raw.replace("/", " ").split():
        match = _DIM_TOKEN.match(token)
        if not match:
            raise ValueError(f"\u65e0\u6cd5\u89e3\u6790\u7684\u91cf\u7eb2\u7247\u6bb5\uff1a{token}")
        symbol, power = match.group(1), match.group(2)
        base = _DIM_SYMBOL.get(symbol.upper())
        if base is None:
            raise ValueError(f"\u672a\u77e5\u91cf\u7eb2\u7b26\u53f7\uff1a{symbol}")
        dims[base] = dims.get(base, 0) + (int(power) if power else 1)
    return {k: v for k, v in dims.items() if v}


def _dims_text(dims: dict[str, int]) -> str:
    """Readable dimension formula, e.g. `M·L²·T⁻²·N⁻¹`."""
    if not dims:
        return "无量纲"
    parts = []
    for dim in BASE:
        power = dims.get(dim)
        if not power:
            continue
        label = {"TH": "T", "A": "A", "Q": "Q"}.get(dim, dim)
        # Plain caret notation: superscript glyphs (notably U+207B) are missing from
        # the embedded text faces, and a dimension formula must never print as tofu.
        parts.append(label if power == 1 else f"{label}^{power}")
    return "·".join(parts)


def describe(dims: dict[str, int], factor: float) -> str:
    """Preferred unit string for a dimension, so records converge on one spelling."""
    for spec in FAMILIES.values():
        if spec["dims"] == dims:
            return spec["preferred"]
    if not dims:
        return "%" if abs(factor - 0.01) < 1e-12 else "无量纲"
    return _dims_text(dims)


# Short aliases are dangerous as prefixes: `k` would swallow `k_times_dt_max`, and
# `t` would swallow `t_max`. Anything this short must match the whole name.
SHORT_ALIAS = 3


def family_of(name: str) -> str | None:
    key = re.sub(r"[^a-z0-9]+", "_", str(name or "").lower()).strip("_")
    if not key:
        return None
    for family, spec in FAMILIES.items():
        for alias in spec["aliases"]:
            if key == alias:
                return family
            if len(alias) <= SHORT_ALIAS:
                continue
            if key.startswith(alias + "_") or key.endswith("_" + alias):
                return family
    return None


def check(quantity: dict) -> list[dict]:
    """Dimension problems for one quantity. Empty list means it is self-consistent."""
    issues: list[dict] = []
    name = str(quantity.get("name") or "").strip()
    if not name:
        issues.append({"code": "missing_name", "text": "量纲项缺少名称"})
        return issues
    value = quantity.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        issues.append({"code": "non_numeric", "text": f"{name} 的值不是数值：{value!r}"})
        return issues
    if not math.isfinite(float(value)):
        issues.append({"code": "non_finite", "text": f"{name} 的值不是有限数：{value}"})

    family = family_of(name)
    unit = quantity.get("unit")
    # A caller may state the dimension explicitly for a domain-specific name; that is
    # how `d_attack` or `RMSF_core` become checkable without teaching the library
    # every field's vocabulary.
    declared = quantity.get("dimension")
    if declared is not None:
        try:
            declared_dims = parse_dimension(str(declared))
        except ValueError as error:
            issues.append({"code": "unparsable_dimension",
                           "text": f"{name} 的 dimension {declared!r} 无法解析：{error}"})
            declared_dims = None
    else:
        declared_dims = None

    if unit is None or str(unit).strip() == "":
        if family and FAMILIES[family]["dims"]:
            issues.append({"code": "missing_unit",
                           "text": f"{name} 缺单位（按名称应为 {FAMILIES[family]['preferred']}）"})
        return issues
    try:
        dims, factor = parse_unit(str(unit))
    except ValueError as error:
        # An unparsable unit is a hard error regardless of whether the name is known.
        issues.append({"code": "unparsable_unit", "text": f"{name} 的单位 {unit!r} 无法解析：{error}"})
        return issues

    if declared_dims is not None:
        if dims != declared_dims:
            issues.append({"code": "dimension_mismatch",
                           "text": f"{name} 与声明的 dimension 不符：{unit!r} 给出 {_dims_text(dims)}，"
                                   f"声明为 {declared!r}（{_dims_text(declared_dims)}）"})
        family = None   # the explicit declaration replaces the alias table
    elif family is None:
        issues.append({"code": "unknown_quantity",
                       "text": f"{name} 不在已知量族里，也没有给出 dimension；"
                               f"单位 {unit!r} 只能确认可解析，不能确认是否配这个量"})

    if family:
        expected = FAMILIES[family]["dims"]
        if expected != dims:
            issues.append({"code": "dimension_mismatch",
                           "text": f"{name} 的量纲不符：{unit!r} 给出 {_dims_text(dims)}，"
                                   f"按名称应为 {_dims_text(expected)}（{FAMILIES[family]['preferred']}）"})
        else:
            preferred = FAMILIES[family]["preferred"]
            try:
                _pdims, pfactor = parse_unit(preferred)
            except ValueError:
                pfactor = factor
            if abs(factor - pfactor) > _UNIT_SCALE_TOL * max(abs(pfactor), 1e-30):
                accepted = quantity.get("unit_acknowledged") is True
                issues.append({"code": "unit_scale_acknowledged" if accepted else "unit_scale",
                               "text": f"{name} 与记录惯例不同：{unit!r}，本库该量用 {preferred}"
                                       + ("（已显式承认，不阻断）" if accepted else
                                          "；如确为有意为之，传 unit_acknowledged=true")})
    elif not dims:
        pass  # a genuinely dimensionless name with a dimensionless unit is fine

    uncertainty = quantity.get("uncertainty")
    if uncertainty is not None:
        if isinstance(uncertainty, bool) or not isinstance(uncertainty, (int, float)):
            issues.append({"code": "bad_uncertainty", "text": f"{name} 的不确定度不是数值"})
        elif float(uncertainty) < 0:
            issues.append({"code": "negative_uncertainty", "text": f"{name} 的不确定度为负"})
        unc_unit = quantity.get("uncertainty_unit")
        if unc_unit and str(unc_unit).strip():
            try:
                udims, _uf = parse_unit(str(unc_unit))
            except ValueError as error:
                issues.append({"code": "unparsable_unit",
                               "text": f"{name} 的不确定度单位 {unc_unit!r} 无法解析：{error}"})
            else:
                if udims != dims:
                    issues.append({"code": "uncertainty_unit_mismatch",
                                   "text": f"{name} 的不确定度单位与数值单位量纲不同：{unc_unit!r}"})
    return issues


def check_all(quantities: list[dict]) -> list[dict]:
    """Per-quantity issues plus cross-quantity conflicts (same name, different unit)."""
    issues: list[dict] = []
    seen: dict[str, tuple[str, str]] = {}
    for index, quantity in enumerate(quantities or []):
        if not isinstance(quantity, dict):
            issues.append({"code": "bad_quantity", "text": f"第 {index + 1} 个量纲项不是对象"})
            continue
        for issue in check(quantity):
            issues.append({**issue, "index": index})
        name = str(quantity.get("name") or "").strip()
        unit = quantity.get("unit")
        if not name or unit in (None, ""):
            continue
        try:
            dims, factor = parse_unit(str(unit))
        except ValueError:
            continue
        # Same dimension but a different scale means the reader cannot compare the
        # numbers directly, even though both spellings are legal.
        signature = (_dims_text(dims), round(math.log10(factor), 9) if factor > 0 else 0.0)
        if name in seen and seen[name][0] != signature:
            # Two scales for one quantity in one record has no legitimate reading.
            issues.append({"code": "inconsistent_unit",
                           "index": index,
                           "text": f"{name} 在不同位置用了不同单位：{seen[name][1]} 与 {unit}，"
                                   f"读者无法直接比较"})
        else:
            seen.setdefault(name, (signature, str(unit)))
    return issues


def _replica_of(quantity: dict):
    """Replica label used to group rows; None for a single-run measurement."""
    replica = quantity.get("replica")
    if replica in (None, ""):
        return None
    if isinstance(replica, bool) or not isinstance(replica, int) or replica < 1:
        return None
    return replica


def duplicate_report(quantities: list[dict]) -> list[dict]:
    """Flag the same name at the same replica twice; that is always a mistake."""
    issues = []
    seen: dict[tuple[str, object], int] = {}
    for index, quantity in enumerate(quantities or []):
        if not isinstance(quantity, dict):
            continue
        name = str(quantity.get("name") or "").strip()
        if not name:
            continue
        key = (name, _replica_of(quantity))
        if key in seen:
            where = "未标副本" if key[1] is None else f"副本 {key[1]}"
            issues.append({"code": "duplicate_quantity",
                           "index": index,
                           "text": f"{name}（{where}）在第 {seen[key] + 1} 项已出现过，"
                                   f"同一副本不应重复记录同名量"})
        else:
            seen[key] = index
    return issues


def summary(quantities: list[dict]) -> list[dict]:
    """Rows for the report table: canonical unit, dimension formula and状态."""
    rows = []
    issues = check_all(quantities) + duplicate_report(quantities)
    by_index: dict[int, list[str]] = {}
    for issue in issues:
        if "index" in issue:
            by_index.setdefault(issue["index"], []).append(issue["text"])
    for index, quantity in enumerate(quantities or []):
        if not isinstance(quantity, dict):
            continue
        unit = quantity.get("unit")
        try:
            dims, factor = parse_unit(str(unit)) if unit not in (None, "") else ({}, 1.0)
            canonical = describe(dims, factor) if unit not in (None, "") else "—"
            formula = _dims_text(dims) if unit not in (None, "") else "—"
        except ValueError:
            canonical, formula = "无法解析", "—"
        problems = by_index.get(index, [])
        codes = {issue["code"] for issue in issues if issue.get("index") == index}
        if not problems:
            status = "通过"
        elif codes - {"unit_scale", "unit_scale_acknowledged"}:
            status = "需修正"
        else:
            status = "惯例差异"
        rows.append({
            "replica": _replica_of(quantity),
            "name": str(quantity.get("name") or ""),
            "value": quantity.get("value"),
            "unit": str(unit) if unit not in (None, "") else "—",
            "canonical": canonical,
            "dimension": formula,
            "status": status,
            "issues": problems,
        })
    return rows
