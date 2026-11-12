#!/usr/bin/env python3
"""Build the review's exact source mutants; the entrywise reference must refuse both.

Native only. Run with nice -n 19 python3 tests/ocean_hydro_reference_mutants.py.
The production tree is never edited; no baselines or generated fixtures are written.
"""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MUTANTS = {
    "drop_A04": (
        "A.m[s6u(0, 4)] = rw * (cx * Fc.z);",
        "A.m[s6u(0, 4)] = 0;",
    ),
    "scale_Fc_x": (
        "const V3 Fc = mul(d, Vk);",
        "V3 Fc = mul(d, Vk); Fc.x *= 0.999f;",
    ),
}


def main():
    with tempfile.TemporaryDirectory(prefix="ocean_hydro_mutants.") as scratch:
        base = Path(scratch)
        source = (ROOT / "src/ocean/hydro_coefficients.hpp").read_text()
        for name, (before, after) in MUTANTS.items():
            assert source.count(before) == 1, f"{name}: mutation target changed"
            case = base / name
            shutil.copytree(ROOT / "src/ocean", case / "ocean")
            (case / "core").symlink_to(ROOT / "src/core", target_is_directory=True)
            (case / "ocean/hydro_coefficients.hpp").write_text(source.replace(before, after))
            binary = case / "reference"
            subprocess.run(
                [os.environ.get("CXX", "g++"), "-O3", "-std=c++20", "-ffp-contract=off",
                 "-DEVO_WORLD_OCEAN", "-I", str(case), "-I", str(ROOT / "src"),
                 str(ROOT / "tools/ocean_hydro_reference.cpp"), "-o", str(binary)],
                check=True, cwd=ROOT,
            )
            result = subprocess.run([str(binary)], text=True, capture_output=True, check=False)
            lines = [line for line in result.stdout.splitlines()
                     if "Abody: input-matched cubature (per entry)" in line]
            assert result.returncode == 1 and len(lines) == 1 and "FAIL" in lines[0], (
                f"{name}: entrywise Abody gate did not reject source mutant\n{result.stdout}\n{result.stderr}"
            )
            print(f"{name}: exit {result.returncode} (expected); {lines[0].strip()}", flush=True)
    print("ocean_hydro_reference_mutants: PASS")


if __name__ == "__main__":
    main()
