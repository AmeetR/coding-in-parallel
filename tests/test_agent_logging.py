from pathlib import Path

from coding_in_parallel import logging as agent_logging


def test_run_logger_creates_files(tmp_path: Path):
    logger = agent_logging.RunLogger(base_dir=tmp_path, run_id="demo")
    logger.log_json("candidates", {"items": [1, 2, 3]})
    logger.log_text("mu", "pre=0\npost=1")
    run_dir = tmp_path / "demo"
    assert run_dir.exists()
    assert (run_dir / "candidates.json").read_text().strip().startswith("{")
    assert "pre=0" in (run_dir / "mu.txt").read_text()


def test_run_logger_events_stream_to_file(tmp_path: Path):
    logger = agent_logging.RunLogger(base_dir=tmp_path, run_id="demo2", stream=False)
    logger.log_event("unit.test", step_id="s1", committed=False)
    events = (tmp_path / "demo2" / "events.ndjson").read_text().splitlines()
    assert events and "\"kind\":\"unit.test\"" in events[0]
