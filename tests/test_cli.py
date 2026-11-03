import subprocess
import sys

import pytest

from x3book.cli import main


def test_no_command_prints_help(capsys):
    assert main([]) == 2
    assert "tune" in capsys.readouterr().out


@pytest.mark.parametrize("cmd", [["tune"], ["check"], ["pdf"], ["merge"], ["flashbook"], ["flashbook", "build"],
                                 ["flashbook", "stats"], ["flashbook", "source"], ["convert"]])
def test_help_for_every_subcommand(cmd, capsys):
    with pytest.raises(SystemExit) as e:
        main(cmd + ["--help"])
    assert e.value.code == 0
    assert "usage: x3book " + " ".join(cmd) in capsys.readouterr().out


def test_python_dash_m():
    r = subprocess.run([sys.executable, "-m", "x3book", "--version"], capture_output=True, text=True)
    assert r.returncode == 0 and "x3book" in r.stdout


def test_no_paid_service_code():
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parent.parent
    for f in list((root / "x3book").glob("*.py")):
        assert not re.search("|".join(["tram" + r"\s*doc", "tram" + "doc", "trạm" + " đọc"]), f.read_text(encoding="utf-8"), re.I), f
