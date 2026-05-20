import subprocess

import pytest

from engines.grok import cdp_worker


def test_port_from_url_extracts_explicit_port():
    assert cdp_worker._port_from_url("http://127.0.0.1:9222") == 9222
    assert cdp_worker._port_from_url("http://localhost:9333/json/version") == 9333


def test_port_from_url_rejects_missing_port():
    with pytest.raises(ValueError, match="CDP URL must include a port"):
        cdp_worker._port_from_url("http://127.0.0.1")
    with pytest.raises(ValueError, match="CDP URL must include a port"):
        cdp_worker._port_from_url("http://127.0.0.1/json/:9222")


def test_kill_stale_cdp_clients_kills_only_node_clients(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        if args == ["netstat", "-ano"]:
            return subprocess.CompletedProcess(
                args,
                0,
                stdout=(
                    "  TCP    127.0.0.1:9222    127.0.0.1:51000    ESTABLISHED    111\r\n"
                    "  TCP    127.0.0.1:9222    127.0.0.1:51001    ESTABLISHED    222\r\n"
                    "  TCP    127.0.0.1:51005   127.0.0.1:9222     ESTABLISHED    666\r\n"
                    "  TCP    127.0.0.1:9222    127.0.0.1:51002    TIME_WAIT       333\r\n"
                    "  TCP    127.0.0.1:92222   127.0.0.1:51004    ESTABLISHED    555\r\n"
                    "  TCP    127.0.0.1:9333    127.0.0.1:51003    ESTABLISHED    444\r\n"
                ),
            )
        if args[:2] == ["tasklist", "/FI"] and "111" in args[2]:
            return subprocess.CompletedProcess(args, 0, stdout='"node.exe","111","Console"\r\n')
        if args[:2] == ["tasklist", "/FI"] and "222" in args[2]:
            return subprocess.CompletedProcess(args, 0, stdout='"brave.exe","222","Console"\r\n')
        if args[:3] == ["wmic", "process", "where"] and args[3] == "ProcessId=111":
            return subprocess.CompletedProcess(
                args,
                0,
                stdout="CommandLine=C:\\tools\\node.exe C:\\patchright\\driver.js\r\n",
            )
        if args[:2] == ["tasklist", "/FI"] and "666" in args[2]:
            return subprocess.CompletedProcess(args, 0, stdout='"node.exe","666","Console"\r\n')
        if args[:3] == ["wmic", "process", "where"] and args[3] == "ProcessId=666":
            return subprocess.CompletedProcess(args, 0, stdout="")
        if args[:3] == ["powershell", "-NoProfile", "-Command"] and "ProcessId=666" in args[3]:
            return subprocess.CompletedProcess(
                args,
                0,
                stdout="C:\\tools\\node.exe C:\\playwright\\driver.js\r\n",
            )
        if args[:2] == ["taskkill", "/F"]:
            return subprocess.CompletedProcess(args, 0, stdout="")
        raise AssertionError(f"unexpected subprocess call: {args!r}")

    monkeypatch.setattr(cdp_worker.subprocess, "run", fake_run)
    monkeypatch.setenv("STORY_VIDEO_KILL_STALE_CDP", "1")

    assert cdp_worker.kill_stale_cdp_clients(9222) == 2
    killed_pids = {
        args[-1]
        for args, kwargs in calls
        if args[:3] == ["taskkill", "/F", "/PID"] and kwargs.get("timeout") == 5
    }
    assert killed_pids == {"111", "666"}
    assert all("222" not in args for args, _kwargs in calls if args[:2] == ["taskkill", "/F"])


def test_kill_stale_cdp_clients_is_opt_in(monkeypatch):
    monkeypatch.delenv("STORY_VIDEO_KILL_STALE_CDP", raising=False)

    def fake_run(args, **kwargs):
        raise AssertionError("cleanup should not run without opt-in env")

    monkeypatch.setattr(cdp_worker.subprocess, "run", fake_run)

    assert cdp_worker.kill_stale_cdp_clients(9222) == 0
