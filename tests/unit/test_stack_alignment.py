from pathlib import Path


def test_preferred_stack_alignment():
    project_root = Path(__file__).resolve().parents[2]

    ml_engine = (project_root / "backend" / "ml_engine" / "__init__.py").read_text(encoding="utf-8")
    assert "RandomForestClassifier" in ml_engine
    assert "XGBClassifier" not in ml_engine

    env_example = (project_root / ".env.example").read_text(encoding="utf-8")
    assert "mysql" in env_example.lower()
    assert "openflow" in env_example.lower()
    assert "ryu" in env_example.lower()
