"""test_build.py — Contract tests for Claude Team ZIP packaging.

exports: none (unittest TestCase classes via discovery)
used_by: python3 -m unittest skills/_resources/scripts/test_build.py
rules:   Build into a temp copy of the repo layout; never overwrite dist/ from tests.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | packaging contract tests
agent:   claude-opus-5-5 | anthropic | 2026-09-28 | s_20260928_packs | five-package split: partition, isolation, refusals
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_app_skills as B  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
PILOT = "skill-017-negative-keyword-conflict-detection"


class Build(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        for d in ("ads", "command-center", "skills"):
            shutil.copytree(REPO / d, root / d, ignore=shutil.ignore_patterns("*.zip", "__pycache__"))
        cls.root = root
        cls.outs = B.build(root)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_every_zip_has_one_root_folder_matching_name_with_skill_md(self):
        for p in self.outs:
            names = zipfile.ZipFile(p).namelist()
            roots = {n.split("/", 1)[0] for n in names}
            self.assertEqual(len(roots), 1, p.name)
            self.assertIn(f"{roots.pop()}/SKILL.md", names, p.name)
            self.assertEqual(sum(n.rsplit("/", 1)[-1] == "SKILL.md" for n in names), 1,
                             f"{p.name}: upload contract allows exactly one SKILL.md")
            self.assertFalse(any("/tests/" in n or "__pycache__" in n or n.endswith(".zip") for n in names), p.name)

    def test_standalone_runs_from_clean_extraction(self):
        z = self.root / "dist" / "skills" / f"{PILOT}.zip"
        with tempfile.TemporaryDirectory() as t:
            zipfile.ZipFile(z).extractall(t)
            skill = Path(t) / PILOT
            md = (skill / "SKILL.md").read_text()
            self.assertNotIn("../_resources", md)
            self.assertIn("scripts/check.py run", md)
            fx = REPO / "skills/_selftest/fixture/scenarios/negative_order"
            r = subprocess.run([sys.executable, str(skill / "scripts/check.py"), "--export", str(fx / "export"),
                                "--profile", str(fx / "profile.yaml"), "--out", str(Path(t) / "out")],
                               capture_output=True, text=True, cwd=t)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((Path(t) / "out/result.json").is_file())

    def test_bundle_is_deterministic(self):
        first = (self.root / "dist/ads.zip").read_bytes()
        B.build(self.root)
        self.assertEqual(first, (self.root / "dist/ads.zip").read_bytes())

    def test_every_recipe_is_in_exactly_one_package(self):
        recipes = {p.name for p in (self.root / "skills").iterdir() if p.is_dir() and p.name.startswith("skill-")}
        found = []
        for pack in B.PACKS:
            names = zipfile.ZipFile(self.root / "dist" / f"{pack}.zip").namelist()
            found += sorted({n.split("/")[2] for n in names if n.startswith(f"{pack}/skills/skill-")})
            self.assertIn(f"{pack}/skills/_resources/runtime/adsrun/cli.py", names, pack)
        self.assertEqual(sorted(found), sorted(recipes))
        packs_md = zipfile.ZipFile(self.root / "dist/ads.zip").read("ads/skills/PACKS.md").decode()
        self.assertEqual(packs_md.count("| skill-"), len(recipes))

    def test_a_package_runs_its_recipe_when_extracted_alone(self):
        pack = next(p for p in B.PACKS if f"{p}/skills/{PILOT}/{B.NESTED_SKILL}"
                    in zipfile.ZipFile(self.root / "dist" / f"{p}.zip").namelist())
        self.assertNotEqual(pack, "ads")
        with tempfile.TemporaryDirectory() as t:
            zipfile.ZipFile(self.root / "dist" / f"{pack}.zip").extractall(t)
            fx = REPO / "skills/_selftest/fixture/scenarios/negative_order"
            r = subprocess.run([sys.executable, str(Path(t) / pack / "skills" / PILOT / "scripts/check.py"), "run",
                                "--export", str(fx / "export"), "--profile", str(fx / "profile.yaml"),
                                "--out", str(Path(t) / "out")], capture_output=True, text=True, cwd=t)
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_unassigned_category_and_broken_resource_link_are_refused(self):
        with tempfile.TemporaryDirectory() as t:
            skills = Path(t) / "skills"
            shutil.copytree(self.root / "skills" / PILOT, skills / PILOT)
            md = skills / PILOT / "SKILL.md"
            md.write_text(B.CATEGORY_RE.sub("  category: nowhere", md.read_text(), count=1))
            with self.assertRaises(ValueError):
                B._recipe_packs(skills)
        with self.assertRaises(ValueError):
            B._check_links("p", {"p/skills/r/SKILL.md": b"see ../_resources/MISSING.md"})

    def test_long_description_is_rejected(self):
        with self.assertRaises(ValueError):
            B._check_contract("x", "a" * 201, "t")
        with self.assertRaises(ValueError):
            B._check_contract("Bad Name", "ok", "t")


if __name__ == "__main__":
    unittest.main()
