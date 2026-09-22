from pyta_lsp.server import Settings


def test_defaults() -> None:
    s = Settings.from_dict(None)
    assert (s.run_on_save, s.run_on_open, s.config_path) == (True, True, "")


def test_flat_payload() -> None:
    s = Settings.from_dict({"runOnSave": False, "runOnOpen": False, "configPath": "x.txt"})
    assert (s.run_on_save, s.run_on_open, s.config_path) == (False, False, "x.txt")


def test_nested_payload_from_did_change_configuration() -> None:
    s = Settings.from_dict({"pythonta": {"runOnSave": False, "configPath": None}})
    assert (s.run_on_save, s.run_on_open, s.config_path) == (False, True, "")


def test_garbage_payload_falls_back_to_defaults() -> None:
    assert Settings.from_dict("nonsense").run_on_save is True
    assert Settings.from_dict(["a"]).run_on_open is True
