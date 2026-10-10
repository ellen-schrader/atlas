"""The VarCon importer behind the spelling_variants migration (offline)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "varcon_to_sql", Path(__file__).parent.parent / "scripts" / "varcon_to_sql.py"
)
varcon = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(varcon)

SAMPLE = """\
# tumor <verified> (level 35)
A Cv DV: tumor / B C D: tumour
A Cv DV: tumors / B C D: tumours
A Cv DV: tumor's / B C D: tumour's

# fetal <verified> (level 35)
A B C Z: fetal / Bv ZV: foetal

# characterize <verified> (level 35)
A Z: characterize / B: characterise

# acknowledgment <verified> (level 35)
A Cv: acknowledgment / Av B C: acknowledgement

# caulk (level 50)
A B: caulk / Av: calk

# practice <verified> (level 35)
A B C: practice / AV Cv: practise | <N>
A Cv: practice / AV B C: practise | <V>

# obscure (level 95)
A: obscurely / B: obscurelie

# ert (level 70)
A: ert / B: ret

# esophagitis (level 70)
A Dv: esophagitis / B D: oesophagitis

# zorpish (level 70)
A: zorpish / B: blargish

# draft <verified> (level 35)
A: draft / B: draught

# draught (level 95)
A: draught
"""


def test_keeps_preferred_and_common_british_spellings():
    pairs = varcon.pairs(SAMPLE, max_level=80)
    assert pairs["tumour"] == "tumor"
    assert pairs["tumours"] == "tumors"
    assert pairs["characterise"] == "characterize"
    assert pairs["acknowledgement"] == "acknowledgment"
    assert pairs["foetal"] == "fetal"  # a common ("v") British variant
    assert pairs["practise"] == "practice"  # verb sense


def test_drops_what_should_not_be_rewritten():
    pairs = varcon.pairs(SAMPLE, max_level=80)
    assert "tumour's" not in pairs  # possessives
    assert "calk" not in pairs and "caulk" not in pairs  # no British/American split
    assert "tumor" not in pairs and "fetal" not in pairs  # American words are never keys
    assert "obscurelie" not in pairs  # above the level cutoff


def test_supplement_covers_words_varcon_lacks():
    assert varcon.pairs("", max_level=80)["oesophageal"] == "esophageal"


def test_render_carries_provenance(tmp_path):
    src = tmp_path / "varcon.txt"
    src.write_text(SAMPLE, encoding="latin-1")
    sql = varcon.render({"tumour": "tumor"}, src, 80)
    assert "sha256" in sql and "Kevin Atkinson" in sql and "THIRD_PARTY_NOTICES.md" in sql
    assert "('tumour', 'tumor')" in sql


def test_unverified_clusters_need_a_real_spelling_pattern():
    pairs = varcon.pairs(SAMPLE, max_level=80)
    # Fragment from an unverified cluster: would rewrite the RET gene to "ert".
    assert "ret" not in pairs
    # Unverified but a plain oe -> e change: kept.
    assert pairs["oesophagitis"] == "esophagitis"
    # Unverified and no spelling pattern explains it: dropped.
    assert "blargish" not in pairs


def test_a_british_form_that_is_american_at_any_level_is_left_alone():
    # "draught" is a preferred American spelling in a level-95 entry, above the
    # cutoff; it still counts, so draught -> draft is not imported.
    assert "draught" not in varcon.pairs(SAMPLE, max_level=80)


def test_fits_pattern():
    assert varcon.fits_pattern("haematoma", "hematoma")
    assert varcon.fits_pattern("centred", "centered")
    assert varcon.fits_pattern("centring", "centering")
    assert varcon.fits_pattern("fibres", "fibers")
    assert varcon.fits_pattern("favoured", "favored")
    assert varcon.fits_pattern("colouring", "coloring")
    assert varcon.fits_pattern("sulphate", "sulfate")
    assert not varcon.fits_pattern("oesophagitis", "esofagitis")
    assert not varcon.fits_pattern("prev", "perv")
